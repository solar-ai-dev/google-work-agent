"""Runtime R2 handlers: V2 MODIFY_REVIEW and V2-only persistence projection.

This module deliberately does not activate ProductionV2GraphComposition or
change package exports. Runtime R3 owns final composition/export wiring.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from google_work_agent.adapters.langgraph.production_v2_graph import ProductionGraphStateV2
from google_work_agent.adapters.langgraph.production_v2_runtime import (
    ProductionV2RuntimeBindingError,
    ProductionV2RuntimeDependencies,
    ProductionV2RuntimeHandlers,
    apply_v2_router_reentry,
)
from google_work_agent.application.workflows.contracts import (
    BudgetDecision,
    RunBudgetV1,
    approve_planning_revision,
)
from google_work_agent.application.workflows.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    RequestIntentV2,
    RetrievalResultV1,
    SubgraphReturnV2,
)
from google_work_agent.application.workflows.modify_review_v2 import (
    ModifyReviewDurableSnapshot,
    ModifyReviewV2Error,
    durable_review_status_for_v2,
    reconstruct_modified_action_plan_v2,
)
from google_work_agent.application.workflows.planning_persistence_v2 import (
    V2PersistenceProjectionError,
    project_action_plan_v2_for_persistence,
)
from google_work_agent.application.workflows.planning_plan_assembler import ActionPlanDraftV2
from google_work_agent.application.workflows.post_retrieval_supervisor_v2 import (
    route_review_return_v2,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.ports import PlanReviewStatus, ResourceRefRecord, WorkflowStartRequest


ModifyReviewSnapshotLoader = Callable[[str, str, int], ModifyReviewDurableSnapshot]
StoreModifyReviewResult = Callable[[str, int, PlanReviewStatus], bool]
BeginModifyReplan = Callable[[str, int, PlanReviewStatus], bool]
PersistProjectedPlan = Callable[[ProductionGraphStateV2, ActionPlanDraftV1], str]
RunResourceRefReader = Callable[[str], Mapping[str, ResourceRefRecord]]


@dataclass(frozen=True, slots=True)
class ProductionV2R2RuntimeDependencies:
    """R2-only durable boundaries; R3 will bind them into the final graph."""

    base: ProductionV2RuntimeDependencies
    modify_review_snapshot_loader: ModifyReviewSnapshotLoader
    store_modify_review_result: StoreModifyReviewResult
    begin_modify_replan: BeginModifyReplan
    persist_projected_plan: PersistProjectedPlan
    resource_refs_by_handle_reader: RunResourceRefReader


class ProductionV2R2RuntimeHandlers(ProductionV2RuntimeHandlers):
    """Complete post-Retrieval V2 handlers without performing the R3 cut-over."""

    def __init__(self, dependencies: ProductionV2R2RuntimeDependencies) -> None:
        super().__init__(dependencies.base)
        self._r2 = dependencies

    def prepare_modify_review_v2(
        self,
        state: ProductionGraphStateV2,
        *,
        plan_id: str,
        review_version: int,
    ) -> dict[str, object]:
        """Reconstruct the user's durable edit as a new ActionPlanDraftV2 revision."""

        request = _request(state)
        current_plan = _action_plan(state.get("planning_result"), "MODIFY_REVIEW")
        tool_route_plan = cast(
            ToolRoutePlanV2,
            _required_mapping(state.get("tool_route_plan"), "tool_route_plan"),
        )
        work_analysis_result = cast(
            WorkAnalysisResultV2,
            _required_mapping(state.get("work_analysis_result"), "work_analysis_result"),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping(state.get("retrieval_result"), "retrieval_result"),
        )
        revision_budget = approve_planning_revision(_retry_budget(state))
        if revision_budget["decision"] == BudgetDecision.DENY.value:
            return _domain_reconcile("MODIFY_REVIEW_BUDGET_EXHAUSTED")

        try:
            durable = self._r2.modify_review_snapshot_loader(
                request.run_id, plan_id, review_version
            )
            reconstructed = reconstruct_modified_action_plan_v2(
                run_id=request.run_id,
                plan_id=plan_id,
                review_version=review_version,
                current_plan=current_plan,
                tool_route_plan=tool_route_plan,
                work_analysis_result=work_analysis_result,
                retrieval_result=retrieval_result,
                durable=durable,
            )
        except (ModifyReviewV2Error, LookupError, ValueError) as exc:
            return _domain_reconcile(str(exc))

        return {
            "planning_result": reconstructed,
            "plan_review_result": None,
            "approved_plan_id": plan_id,
            "__modify_review_plan_id__": plan_id,
            "__modify_review_version__": review_version,
            "__v2_modify_review_plan_revision__": reconstructed["meta"]["revision"],
            "retry_budget": revision_budget["run_budget"],
            "__target__": "modify_review",
            "__logical_target__": "modify_review",
        }

    def _modify_review_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        """Review the reconstructed V2 plan; never invoke a legacy Review artifact."""

        request = _request(state)
        plan_id, review_version = _modify_review_identity(state)
        planning_result = _action_plan(state.get("planning_result"), "MODIFY_REVIEW Review")
        expected_revision = state.get("__v2_modify_review_plan_revision__")
        if planning_result["meta"]["artifact_id"] != plan_id or (
            not isinstance(expected_revision, int)
            or planning_result["meta"]["revision"] != expected_revision
        ):
            return _domain_reconcile("STALE_MODIFY_REVIEW_V2_PLAN")

        request_intent = cast(
            RequestIntentV2,
            _required_mapping(state.get("request_intent"), "request_intent"),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping(state.get("retrieval_result"), "retrieval_result"),
        )
        work_analysis_result = cast(
            WorkAnalysisResultV2,
            _required_mapping(state.get("work_analysis_result"), "work_analysis_result"),
        )
        evidence = _evidence(state, retrieval_result)
        confirmation = self._deps.confirmation_context_resolver(state, "REVIEW")
        if confirmation is not None and confirmation[1].get("subgraph_id") != "REVIEW":
            raise ProductionV2RuntimeBindingError(
                "modify review confirmation must resume the REVIEW owner"
            )
        try:
            envelope = self._deps.review_producer_factory(request).run(
                request_intent=request_intent,
                retrieval_result=retrieval_result,
                work_analysis_result=work_analysis_result,
                planning_result=planning_result,
                evidence_drafts=evidence,
                interrupt_id=None if confirmation is None else confirmation[0],
                resume_target=None if confirmation is None else confirmation[1],
            )
        except ValueError as exc:
            return _domain_reconcile(f"MODIFY_REVIEW_V2_FAIL_CLOSED:{exc}")

        decision = route_review_return_v2(
            envelope,
            planning_result=planning_result,
            retry_budget=_retry_budget(state),
            block_run=self._deps.block_run,
            budget_block_context=(
                None
                if self._deps.budget_block_context_factory is None
                else self._deps.budget_block_context_factory(state)
            ),
        )
        review = envelope.get("typed_result")
        if not isinstance(review, Mapping) or review.get("schema_version") != 2:
            return _domain_reconcile("MODIFY_REVIEW_V2_RESULT_MISSING")
        typed_review = cast(PlanReviewResultV2, review)
        patch: dict[str, object] = {
            "post_retrieval_return": cast(SubgraphReturnV2[object], envelope),
            "plan_review_result": typed_review,
            "workflow_signal": envelope.get("workflow_signal"),
        }
        if decision["retry_budget"] is not None:
            patch["retry_budget"] = decision["retry_budget"]
        if decision["revision_mode"] is not None:
            patch["__v2_revision_mode__"] = decision["revision_mode"]

        status = typed_review["status"]
        durable_status = durable_review_status_for_v2(typed_review)
        if status == "PASS":
            # PASS is persisted only after V2 Domain Validation also passes.
            return apply_v2_router_reentry(patch, decision)
        if status == "ROUTE_RECONSIDERATION":
            # Migration 0004 has no ROUTE_RECONSIDERATION durable value. Never
            # downgrade it to RETRIEVE_MORE: reconcile the WAITING_APPROVAL
            # generation before Tool Route can safely own the next step.
            return {
                **patch,
                **_domain_reconcile(
                    "MODIFY_ROUTE_RECONSIDERATION_REQUIRES_RECONCILE"
                ),
            }
        if status == "CONFIRM":
            # RequestConfirmation does not accept WAITING_APPROVAL. Preserve
            # the V2 Review result and fail closed until Domain reconciliation
            # moves this generation to a confirmation-capable phase.
            return {**patch, **_domain_reconcile("MODIFY_CONFIRM_REQUIRES_RECONCILE")}
        if durable_status is None or not self._r2.store_modify_review_result(
            plan_id, review_version, durable_status
        ):
            return {**patch, **_domain_reconcile("STALE_MODIFY_REVIEW")}

        if status in {"REVISE", "RETRIEVE_MORE"}:
            if not self._r2.begin_modify_replan(plan_id, review_version, durable_status):
                return {**patch, **_domain_reconcile("STALE_MODIFY_REVIEW_REPLAN")}
            patch["__replan_from_plan_id__"] = plan_id
            patch["__modify_review_plan_id__"] = None
            patch["__modify_review_version__"] = None
            patch["__v2_modify_review_plan_revision__"] = None
        return apply_v2_router_reentry(patch, decision)

    def _domain_validation_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        """DV PASS persists only a V2-derived compatibility projection."""

        patch = super()._domain_validation_v2_node(state)
        if patch.get("__target__") != "waiting_approval":
            return patch

        request = _request(state)
        planning_result = _action_plan(state.get("planning_result"), "V2 persistence")
        modify_plan_id = state.get("__modify_review_plan_id__")
        modify_review_version = state.get("__modify_review_version__")
        if modify_plan_id is not None or modify_review_version is not None:
            plan_id, review_version = _modify_review_identity(state)
            if planning_result["meta"]["artifact_id"] != plan_id:
                return {**patch, **_domain_reconcile("STALE_MODIFY_REVIEW_V2_PLAN")}
            if not self._r2.store_modify_review_result(
                plan_id, review_version, PlanReviewStatus.PASSED
            ):
                return {**patch, **_domain_reconcile("STALE_MODIFY_REVIEW")}
            return {
                **patch,
                "approved_plan_id": plan_id,
                # The reconstructed planning_result remains the checkpoint
                # semantic authority for this exact durable plan generation.
                "__modify_review_plan_id__": None,
                "__modify_review_version__": None,
                "__v2_modify_review_plan_revision__": None,
            }

        request_intent = cast(
            RequestIntentV2,
            _required_mapping(state.get("request_intent"), "request_intent"),
        )
        tool_route_plan = cast(
            ToolRoutePlanV2,
            _required_mapping(state.get("tool_route_plan"), "tool_route_plan"),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping(state.get("retrieval_result"), "retrieval_result"),
        )
        try:
            projection = project_action_plan_v2_for_persistence(
                run_id=request.run_id,
                request_intent=request_intent,
                plan=planning_result,
                tool_route_plan=tool_route_plan,
                evidence_drafts=_evidence(state, retrieval_result),
                resource_refs_by_handle=self._r2.resource_refs_by_handle_reader(
                    request.run_id
                ),
            )
            persisted_plan_id = self._r2.persist_projected_plan(state, projection)
        except (V2PersistenceProjectionError, ValueError, LookupError, RuntimeError) as exc:
            return {**patch, **_domain_reconcile(f"V2_PERSISTENCE_FAIL_CLOSED:{exc}")}
        if not persisted_plan_id:
            return {
                **patch,
                **_domain_reconcile("V2_PERSISTENCE_RETURNED_EMPTY_PLAN_ID"),
            }
        return {**patch, "approved_plan_id": persisted_plan_id}


def _request(state: ProductionGraphStateV2) -> WorkflowStartRequest:
    value = state.get("__request__")
    if not isinstance(value, WorkflowStartRequest):
        raise ProductionV2RuntimeBindingError(
            "Production V2 state is missing WorkflowStartRequest"
        )
    return value


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProductionV2RuntimeBindingError(f"Production V2 state is missing {label}")
    return value


def _action_plan(value: object, label: str) -> ActionPlanDraftV2:
    root = _required_mapping(value, "planning_result")
    if (
        root.get("schema_version") != 2
        or not isinstance(root.get("actions"), list)
        or "answer" in root
    ):
        raise ProductionV2RuntimeBindingError(f"{label} requires ActionPlanDraftV2")
    return cast(ActionPlanDraftV2, root)


def _retry_budget(state: ProductionGraphStateV2) -> RunBudgetV1:
    value = _required_mapping(state.get("retry_budget"), "retry_budget")
    return cast(RunBudgetV1, value)


def _evidence(
    state: ProductionGraphStateV2,
    retrieval_result: RetrievalResultV1,
) -> list[EvidenceDraftV1]:
    raw = state.get("evidence_drafts")
    if not isinstance(raw, list):
        raise ProductionV2RuntimeBindingError(
            "Production V2 state is missing current-run Evidence"
        )
    evidence = cast(list[EvidenceDraftV1], raw)
    expected = list(retrieval_result["evidence_refs"])
    actual = [item.get("evidence_id") for item in evidence]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ProductionV2RuntimeBindingError(
            "current-run Evidence does not match RetrievalResultV1"
        )
    by_id = {item["evidence_id"]: item for item in evidence}
    return [by_id[evidence_id] for evidence_id in expected]


def _modify_review_identity(state: ProductionGraphStateV2) -> tuple[str, int]:
    plan_id = state.get("__modify_review_plan_id__")
    review_version = state.get("__modify_review_version__")
    if not isinstance(plan_id, str) or not plan_id:
        raise ProductionV2RuntimeBindingError("MODIFY_REVIEW plan_id is required")
    if (
        not isinstance(review_version, int)
        or isinstance(review_version, bool)
        or review_version < 0
    ):
        raise ProductionV2RuntimeBindingError("MODIFY_REVIEW review_version is required")
    return plan_id, review_version


def _domain_reconcile(reason: str) -> dict[str, object]:
    return {
        "__target__": "domain_reconcile",
        "__logical_target__": "domain_reconcile",
        "__v2_modify_review_error__": reason,
    }


__all__ = [
    "ProductionV2R2RuntimeDependencies",
    "ProductionV2R2RuntimeHandlers",
]
