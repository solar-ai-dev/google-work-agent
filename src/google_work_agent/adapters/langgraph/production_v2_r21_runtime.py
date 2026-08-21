"""Runtime R2.1 post-approval replan identity closure.

R2 remains the durable MODIFY_REVIEW/V2-persistence boundary.  This subclass
adds only the identity rollover that becomes mandatory after a reviewed durable
plan is superseded.  Final graph/export activation remains Runtime R3 scope.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from google_work_agent.adapters.langgraph.production_v2_graph import ProductionGraphStateV2
from google_work_agent.adapters.langgraph.production_v2_r2_runtime import (
    ProductionV2R2RuntimeDependencies,
    ProductionV2R2RuntimeHandlers,
)
from google_work_agent.adapters.langgraph.production_v2_runtime import (
    ProductionV2RuntimeBindingError,
)
from google_work_agent.application.workflows.handoff_contracts import RetrievalResultV1
from google_work_agent.application.workflows.planning_plan_assembler import ActionPlanDraftV2
from google_work_agent.application.workflows.post_approval_replan_v2 import (
    PostApprovalReplanIdentityV1,
    PostApprovalReplanV2Error,
    begin_post_approval_replan_identity,
    bind_preallocated_identity,
    materialize_fresh_post_approval_revise_plan,
    validate_post_approval_replan_identity,
    validate_preallocated_plan_identity,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.ports import WorkflowStartRequest

_POST_APPROVAL_REPLAN_KEY = "__v2_post_approval_replan_identity__"
FreshIdentityFactory = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class ProductionV2R21RuntimeDependencies:
    """R2 dependencies plus explicit fresh V2 identity factories."""

    base: ProductionV2R2RuntimeDependencies
    fresh_plan_id_factory: FreshIdentityFactory
    fresh_action_id_factory: FreshIdentityFactory


class ProductionV2R21RuntimeHandlers(ProductionV2R2RuntimeHandlers):
    """Separate pre-approval revision identity from post-approval rollover."""

    def __init__(self, dependencies: ProductionV2R21RuntimeDependencies) -> None:
        super().__init__(dependencies.base)
        self._r21 = dependencies

    def _modify_review_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        """Capture the superseded generation only after R2 accepts the replan."""

        source_plan = _action_plan(state.get("planning_result"), "post-approval MODIFY_REVIEW")
        result = super()._modify_review_v2_node(state)
        source_plan_id = source_plan["meta"]["artifact_id"]
        if result.get("__replan_from_plan_id__") != source_plan_id:
            return result

        review = _review_from_return(result.get("post_retrieval_return"))
        status = review["status"]
        if status not in {"REVISE", "RETRIEVE_MORE"}:
            return result
        try:
            identity = begin_post_approval_replan_identity(
                source_plan=source_plan,
                trigger=cast(str, status),
            )
        except PostApprovalReplanV2Error as exc:
            return {**result, **_domain_reconcile(f"POST_APPROVAL_REPLAN_IDENTITY:{exc}")}
        return {**result, _POST_APPROVAL_REPLAN_KEY: identity}

    def _planning_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        """Freshen identity only for a post-approval rollover generation.

        With no R2.1 marker, the R1/R2 Planning node is used unchanged; normal
        pre-approval Review.REVISE therefore keeps artifact/action identity and
        increments only the artifact revision.
        """

        raw_identity = state.get(_POST_APPROVAL_REPLAN_KEY)
        if raw_identity is None:
            return super()._planning_v2_node(state)
        try:
            identity = validate_post_approval_replan_identity(raw_identity)
        except PostApprovalReplanV2Error as exc:
            return _domain_reconcile(f"POST_APPROVAL_REPLAN_IDENTITY:{exc}")
        if state.get("__replan_from_plan_id__") != identity["source_plan_id"]:
            return _domain_reconcile("POST_APPROVAL_REPLAN_SOURCE_PLAN_MISMATCH")

        request = _request(state)
        source_plan: ActionPlanDraftV2 | None = None
        source_review: PlanReviewResultV2 | None = None
        if identity["phase"] == "ROLLOVER_REQUIRED" and identity["trigger"] == "REVISE":
            source_plan = _action_plan(
                state.get("planning_result"),
                "post-approval REVISE source",
            )
            _require_source_identity(identity, source_plan)
            source_review = _review_result(state.get("plan_review_result"), required_status="REVISE")

        try:
            patch = super()._planning_v2_node(state)
        except ValueError as exc:
            return _domain_reconcile(f"POST_APPROVAL_REPLAN_PLANNING:{exc}")
        raw_plan = patch.get("planning_result")
        if raw_plan is None:
            return patch
        produced_plan = _action_plan(raw_plan, "post-approval Planning result")

        try:
            if identity["phase"] == "ROLLOVER_REQUIRED" and identity["trigger"] == "REVISE":
                assert source_plan is not None
                assert source_review is not None
                produced_plan = materialize_fresh_post_approval_revise_plan(
                    source_modified_plan=source_plan,
                    corrected_plan=produced_plan,
                    review_result=source_review,
                    tool_route_plan=cast(
                        ToolRoutePlanV2,
                        _required_mapping(state.get("tool_route_plan"), "tool_route_plan"),
                    ),
                    work_analysis_result=cast(
                        WorkAnalysisResultV2,
                        _required_mapping(
                            state.get("work_analysis_result"),
                            "work_analysis_result",
                        ),
                    ),
                    retrieval_result=cast(
                        RetrievalResultV1,
                        _required_mapping(state.get("retrieval_result"), "retrieval_result"),
                    ),
                    plan_id_factory=lambda: self._r21.fresh_plan_id_factory(request.run_id),
                    action_id_factory=lambda: self._r21.fresh_action_id_factory(request.run_id),
                )
            identity = bind_preallocated_identity(identity=identity, plan=produced_plan)
        except PostApprovalReplanV2Error as exc:
            return {**patch, **_domain_reconcile(f"POST_APPROVAL_REPLAN_ROLLOVER:{exc}")}

        return {
            **patch,
            "planning_result": produced_plan,
            _POST_APPROVAL_REPLAN_KEY: identity,
        }

    def _domain_validation_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        """Prove reviewed V2 ids equal the approval-generation durable ids."""

        patch = super()._domain_validation_v2_node(state)
        raw_identity = state.get(_POST_APPROVAL_REPLAN_KEY)
        if raw_identity is None or patch.get("__target__") != "waiting_approval":
            return patch
        try:
            identity = validate_post_approval_replan_identity(raw_identity)
            plan = _action_plan(state.get("planning_result"), "post-approval DV")
            plan_id, action_ids = _plan_identity(plan)
            validate_preallocated_plan_identity(
                identity=identity,
                plan_id=plan_id,
                action_ids=action_ids,
            )
        except PostApprovalReplanV2Error as exc:
            return {**patch, **_domain_reconcile(f"POST_APPROVAL_DV_IDENTITY:{exc}")}
        approved_plan_id = patch.get("approved_plan_id")
        if approved_plan_id != plan_id:
            return {
                **patch,
                **_domain_reconcile("APPROVAL_PLAN_ID_DIFFERS_FROM_REVIEWED_V2_ID"),
            }
        return patch


def _review_from_return(value: object) -> PlanReviewResultV2:
    if not isinstance(value, Mapping):
        raise ProductionV2RuntimeBindingError("post-retrieval return is missing")
    typed = value.get("typed_result")
    return _review_result(typed, required_status=None)


def _review_result(
    value: object,
    *,
    required_status: str | None,
) -> PlanReviewResultV2:
    root = _required_mapping(value, "plan_review_result")
    status = root.get("status")
    if root.get("schema_version") != 2 or not isinstance(status, str):
        raise ProductionV2RuntimeBindingError("PlanReviewResultV2 is invalid")
    if required_status is not None and status != required_status:
        raise ProductionV2RuntimeBindingError(
            f"PlanReviewResultV2 status must be {required_status}"
        )
    return cast(PlanReviewResultV2, root)


def _require_source_identity(
    identity: PostApprovalReplanIdentityV1,
    plan: ActionPlanDraftV2,
) -> None:
    plan_id, action_ids = _plan_identity(plan)
    if plan_id != identity["source_plan_id"] or action_ids != identity["source_action_ids"]:
        raise PostApprovalReplanV2Error(
            "post-approval REVISE source no longer matches the superseded durable generation"
        )


def _plan_identity(plan: ActionPlanDraftV2) -> tuple[str, list[str]]:
    meta = _required_mapping(plan.get("meta"), "planning_result.meta")
    plan_id = meta.get("artifact_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise PostApprovalReplanV2Error("planning_result artifact id is invalid")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise PostApprovalReplanV2Error("planning_result actions are missing")
    action_ids: list[str] = []
    for action in actions:
        if not isinstance(action, Mapping):
            raise PostApprovalReplanV2Error("planning_result action is invalid")
        action_id = action.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise PostApprovalReplanV2Error("planning_result action id is invalid")
        action_ids.append(action_id)
    if len(action_ids) != len(set(action_ids)):
        raise PostApprovalReplanV2Error("planning_result action ids are duplicated")
    return plan_id, action_ids


def _action_plan(value: object, label: str) -> ActionPlanDraftV2:
    root = _required_mapping(value, "planning_result")
    if root.get("schema_version") != 2 or not isinstance(root.get("actions"), list) or "answer" in root:
        raise ProductionV2RuntimeBindingError(f"{label} requires ActionPlanDraftV2")
    return cast(ActionPlanDraftV2, root)


def _request(state: ProductionGraphStateV2) -> WorkflowStartRequest:
    value = state.get("__request__")
    if not isinstance(value, WorkflowStartRequest):
        raise ProductionV2RuntimeBindingError("Production V2 state is missing WorkflowStartRequest")
    return value


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProductionV2RuntimeBindingError(f"Production V2 state is missing {label}")
    return value


def _domain_reconcile(reason: str) -> dict[str, object]:
    return {
        "__target__": "domain_reconcile",
        "__logical_target__": "domain_reconcile",
        "__v2_post_approval_replan_error__": reason,
    }


__all__ = [
    "ProductionV2R21RuntimeDependencies",
    "ProductionV2R21RuntimeHandlers",
]
