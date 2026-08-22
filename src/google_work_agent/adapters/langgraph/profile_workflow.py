"""Bounded SIX_ROLE production V2 node handlers and deterministic state handoff.

This module binds the already-built Runtime V2 application producers to the
post-Retrieval LangGraph state without activating the final product graph.
It intentionally leaves ``adapters.langgraph.__init__`` and InvocationCoordinator
unchanged for Runtime R2/R3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from google_work_agent.adapters.langgraph.workflow_graph import (
    ProductionGraphStateV2,
)
from google_work_agent.application.orchestration.contracts import (
    DomainValidationOutputV1,
    PolicyConfirmationReceiptV1,
    RunBudgetV1,
)
from google_work_agent.application.orchestration.domain_output_validation import (
    RunScopedResourceIdentityReader,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalResultV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
    SubgraphReturnV2,
    WorkflowSignalV1,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    ActionPlanDraftV2,
)
from google_work_agent.application.orchestration.revise_planning_output import (
    PlanningV2RevisionProducer,
)
from google_work_agent.application.orchestration.planning_invocation import (
    PlanningV2Producer,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PlanningResultV2,
    validate_work_analysis_return_v2,
)
from google_work_agent.application.orchestration.post_retrieval_invocation import (
    PostRetrievalRuntimeV2Boundary,
)
from google_work_agent.application.orchestration.supervise_post_retrieval import (
    BlockRunExecutor,
    PostRetrievalRouteDecisionV2,
    RevisionBudgetBlockContextV1,
    route_planning_return_v2,
    route_review_return_v2,
    route_work_analysis_return_v2,
)
from google_work_agent.application.orchestration.review_invocation import ReviewV2Producer
from google_work_agent.application.orchestration.state_artifacts import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.orchestration.tool_routing import ToolRoutePlanV2
from google_work_agent.application.orchestration.assemble_work_analysis_output import (
    RelationValidator,
    RetrievalNeedSatisfier,
    WorkAnalysisV2CandidateProvider,
    WorkAnalysisV2NodeChain,
    build_frozen_route_connector_resolver,
)
from google_work_agent.ports import WorkflowStartRequest


class ProductionV2RuntimeBindingError(ValueError):
    """Current invocation state cannot satisfy a Runtime V2 node contract."""


ConfirmationContextResolver = Callable[
    [ProductionGraphStateV2, str],
    tuple[str, RegisteredResumeTargetRefV1] | None,
]
ArtifactIdFactory = Callable[[str, str], str]
WorkAnalysisProviderFactory = Callable[
    [WorkflowStartRequest], WorkAnalysisV2CandidateProvider
]
PlanningProducerFactory = Callable[[WorkflowStartRequest], PlanningV2Producer]
PlanningRevisionProducerFactory = Callable[
    [WorkflowStartRequest], PlanningV2RevisionProducer
]
ReviewProducerFactory = Callable[[WorkflowStartRequest], ReviewV2Producer]
RuntimeBoundaryFactory = Callable[
    [WorkflowStartRequest], PostRetrievalRuntimeV2Boundary
]
ResourceIdentityReaderFactory = Callable[
    [str], RunScopedResourceIdentityReader
]
BudgetBlockContextFactory = Callable[
    [ProductionGraphStateV2], RevisionBudgetBlockContextV1
]


@dataclass(frozen=True, slots=True)
class ProductionV2RuntimeDependencies:
    """Factories keep all mutable/runtime authority invocation-scoped."""

    work_analysis_provider_factory: WorkAnalysisProviderFactory
    planning_producer_factory: PlanningProducerFactory
    planning_revision_producer_factory: PlanningRevisionProducerFactory
    review_producer_factory: ReviewProducerFactory
    runtime_boundary_factory: RuntimeBoundaryFactory
    resource_identity_reader_factory: ResourceIdentityReaderFactory
    artifact_id_factory: ArtifactIdFactory
    confirmation_context_resolver: ConfirmationContextResolver
    relation_validator: RelationValidator | None = None
    retrieval_need_satisfier: RetrievalNeedSatisfier | None = None
    block_run: BlockRunExecutor | None = None
    budget_block_context_factory: BudgetBlockContextFactory | None = None


class ProductionV2RuntimeHandlers:
    """Concrete R1 handlers for Work Analysis, Planning, Review and DV V2."""

    def __init__(self, dependencies: ProductionV2RuntimeDependencies) -> None:
        self._deps = dependencies

    def _work_analysis_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        request = _request(state)
        request_intent = _required_mapping_value(
            state.get("request_intent"),
            "request_intent",
        )
        tool_route_plan = cast(
            ToolRoutePlanV2,
            _required_mapping_value(
                state.get("tool_route_plan"),
                "tool_route_plan",
            ),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping_value(
                state.get("retrieval_result"),
                "retrieval_result",
            ),
        )
        evidence = _evidence(state, retrieval_result)

        # Runtime authority: rebuilt from the current frozen ToolRoutePlanV2 on
        # every invocation. No resolver survives in graph/checkpoint state.
        connector_resolver = build_frozen_route_connector_resolver(tool_route_plan)
        chain = WorkAnalysisV2NodeChain(
            candidate_provider=self._deps.work_analysis_provider_factory(request),
            connector_for_resource_handle=connector_resolver,
            relation_validator=self._deps.relation_validator,
            retrieval_need_satisfier=self._deps.retrieval_need_satisfier,
        )
        confirmation = _confirmation_context(
            state,
            owner="WORK_ANALYSIS",
            resolver=self._deps.confirmation_context_resolver,
        )

        # IMP-200~209 provenance is not yet complete on this branch. Receipt
        # shape or APPROVED status alone is not authorization. Compute the
        # fail-closed receipt projection once, then reuse that exact list for
        # both official WorkAnalysisResultV2 receipt refs and meta lineage.
        validated_receipt_refs = _validated_work_analysis_receipt_refs(
            _policy_receipts(state)
        )
        work_analysis_meta = _work_analysis_meta(
            state,
            artifact_id=self._deps.artifact_id_factory(
                "work_analysis",
                request.run_id,
            ),
            policy_confirmation_receipt_refs=validated_receipt_refs,
        )

        result = chain.run(
            user_request=request.request_text,
            request_intent=cast(RequestIntentV2, request_intent),
            retrieval_result=retrieval_result,
            evidence_drafts=evidence,
            meta=work_analysis_meta,
            policy_confirmation_receipt_refs=validated_receipt_refs,
            interrupt_id=None if confirmation is None else confirmation[0],
            resume_target=None if confirmation is None else confirmation[1],
        )
        envelope = _work_analysis_envelope(result)
        decision = route_work_analysis_return_v2(envelope)
        patch: dict[str, object] = {
            "post_retrieval_return": envelope,
            "workflow_signal": envelope["workflow_signal"],
        }
        if envelope["disposition"] == "COMPLETE":
            patch["work_analysis_result"] = envelope["typed_result"]
        return _apply_post_retrieval_decision(patch, decision)

    def _planning_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        request = _request(state)
        request_intent = cast(
            RequestIntentV2,
            _required_mapping_value(state.get("request_intent"), "request_intent"),
        )
        tool_route_plan = cast(
            ToolRoutePlanV2,
            _required_mapping_value(state.get("tool_route_plan"), "tool_route_plan"),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping_value(state.get("retrieval_result"), "retrieval_result"),
        )
        work_analysis_result = cast(
            WorkAnalysisResultV2,
            _required_mapping_value(
                state.get("work_analysis_result"),
                "work_analysis_result",
            ),
        )
        evidence = _evidence(state, retrieval_result)
        confirmation = _confirmation_context(
            state,
            owner="PLANNING",
            resolver=self._deps.confirmation_context_resolver,
        )
        revision_mode = state.get("__v2_revision_mode__")

        if revision_mode is None:
            envelope = self._deps.planning_producer_factory(request).run(
                request=request,
                request_intent=request_intent,
                tool_route_plan=tool_route_plan,
                retrieval_result=retrieval_result,
                work_analysis_result=work_analysis_result,
                evidence_drafts=evidence,
                interrupt_id=None if confirmation is None else confirmation[0],
                resume_target=None if confirmation is None else confirmation[1],
            )
        elif revision_mode == "PLAN":
            current_plan = _action_plan(
                state.get("planning_result"),
                label="Planning revision",
            )
            review_result = _review_result(
                state.get("plan_review_result"),
                required_status="REVISE",
            )
            envelope = self._deps.planning_revision_producer_factory(request).run(
                request=request,
                request_intent=request_intent,
                tool_route_plan=tool_route_plan,
                retrieval_result=retrieval_result,
                work_analysis_result=work_analysis_result,
                current_plan=current_plan,
                review_result=review_result,
                evidence_drafts=evidence,
            )
        else:
            # ANSWER revision durable reconstruction is explicitly R2/R3 scope.
            raise ProductionV2RuntimeBindingError(
                f"unsupported R1 planning revision mode: {revision_mode}"
            )

        decision = route_planning_return_v2(envelope)
        patch = {
            "post_retrieval_return": envelope,
            "workflow_signal": envelope["workflow_signal"],
        }
        if envelope["typed_result"] is not None:
            patch["planning_result"] = envelope["typed_result"]
            patch["plan_review_result"] = None
            patch["__v2_revision_mode__"] = None
        return _apply_post_retrieval_decision(patch, decision)

    def _review_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        request = _request(state)
        request_intent = cast(
            RequestIntentV2,
            _required_mapping_value(state.get("request_intent"), "request_intent"),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping_value(state.get("retrieval_result"), "retrieval_result"),
        )
        work_analysis_result = cast(
            WorkAnalysisResultV2,
            _required_mapping_value(
                state.get("work_analysis_result"),
                "work_analysis_result",
            ),
        )
        planning_result = _action_plan(
            state.get("planning_result"),
            label="Review",
        )
        evidence = _evidence(state, retrieval_result)
        confirmation = _confirmation_context(
            state,
            owner="REVIEW",
            resolver=self._deps.confirmation_context_resolver,
        )
        envelope = self._deps.review_producer_factory(request).run(
            request_intent=request_intent,
            retrieval_result=retrieval_result,
            work_analysis_result=work_analysis_result,
            planning_result=planning_result,
            evidence_drafts=evidence,
            interrupt_id=None if confirmation is None else confirmation[0],
            resume_target=None if confirmation is None else confirmation[1],
        )
        budget_context = (
            None
            if self._deps.budget_block_context_factory is None
            else self._deps.budget_block_context_factory(state)
        )
        decision = route_review_return_v2(
            envelope,
            planning_result=planning_result,
            retry_budget=_retry_budget(state),
            block_run=self._deps.block_run,
            budget_block_context=budget_context,
        )
        patch: dict[str, object] = {
            "post_retrieval_return": envelope,
            "plan_review_result": envelope["typed_result"],
            "workflow_signal": envelope["workflow_signal"],
        }
        if decision["retry_budget"] is not None:
            patch["retry_budget"] = decision["retry_budget"]
        if decision["revision_mode"] is not None:
            patch["__v2_revision_mode__"] = decision["revision_mode"]
        return _apply_post_retrieval_decision(patch, decision)

    def _domain_validation_v2_node(
        self,
        state: ProductionGraphStateV2,
    ) -> dict[str, object]:
        request = _request(state)
        planning_result = _action_plan(
            state.get("planning_result"),
            label="Domain Validation",
        )
        review_result = _review_result(
            state.get("plan_review_result"),
            required_status="PASS",
        )
        work_analysis_result = cast(
            WorkAnalysisResultV2,
            _required_mapping_value(
                state.get("work_analysis_result"),
                "work_analysis_result",
            ),
        )
        retrieval_result = cast(
            RetrievalResultV1,
            _required_mapping_value(state.get("retrieval_result"), "retrieval_result"),
        )
        output = self._deps.runtime_boundary_factory(request).domain_validate(
            run_id=request.run_id,
            planning_result=planning_result,
            plan_review=review_result,
            work_analysis_result=work_analysis_result,
            evidence_drafts=_evidence(state, retrieval_result),
            policy_confirmation_receipts=_policy_receipts(state),
            resource_identity_reader=self._deps.resource_identity_reader_factory(
                request.run_id
            ),
        )
        return _domain_validation_patch(output)


def apply_v2_router_reentry(
    state_patch: Mapping[str, object],
    decision: PostRetrievalRouteDecisionV2,
) -> dict[str, object]:
    """Public bounded helper for deterministic V2 back-edge invalidation."""

    return _apply_post_retrieval_decision(dict(state_patch), decision)


def _work_analysis_envelope(
    result: WorkAnalysisResultV2 | WorkflowSignalV1,
) -> SubgraphReturnV2[object]:
    if _looks_like_work_analysis_result(result):
        return cast(
            SubgraphReturnV2[object],
            validate_work_analysis_return_v2(
                {
                    "disposition": "COMPLETE",
                    "typed_result": result,
                    "workflow_signal": None,
                }
            ),
        )
    signal = cast(Mapping[str, object], result)
    kind = signal.get("kind")
    disposition_by_kind = {
        "RETRIEVAL_REQUIRED": "NEEDS_MORE_DATA",
        "CONFIRMATION_REQUIRED": "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED": "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED": "BLOCKED",
    }
    disposition = disposition_by_kind.get(cast(str, kind))
    if disposition is None:
        raise ProductionV2RuntimeBindingError(
            "Work Analysis returned an unsupported workflow signal"
        )
    return cast(
        SubgraphReturnV2[object],
        validate_work_analysis_return_v2(
            {
                "disposition": disposition,
                "typed_result": None,
                "workflow_signal": dict(signal),
            }
        ),
    )


def _domain_validation_patch(
    output: DomainValidationOutputV1,
) -> dict[str, object]:
    result = output["result"]
    envelope: SubgraphReturnV2[DomainValidationOutputV1] = {
        "disposition": result,
        "typed_result": output,
        "workflow_signal": None,
    }
    if result == "REQUIRE_APPROVAL":
        target = "waiting_approval"
        signal = None
    elif result == "BLOCK":
        target = "block_run"
        signal = {
            "kind": "BLOCKED",
            "reason_codes": list(output["reason_codes"]),
        }
        envelope["workflow_signal"] = cast(Any, signal)
    elif result == "ALLOW_READ":
        # Runtime V2 DV receives ActionPlanDraftV2 only. Treat ALLOW_READ as a
        # durable-state reconciliation case, never as success/finalize.
        target = "domain_reconcile"
        signal = None
    else:
        raise ProductionV2RuntimeBindingError(
            f"unknown DomainValidationOutputV1 result: {result}"
        )
    return {
        "post_retrieval_return": envelope,
        "workflow_signal": signal,
        "__target__": target,
        "__logical_target__": target,
    }


def _apply_post_retrieval_decision(
    patch: dict[str, object],
    decision: PostRetrievalRouteDecisionV2,
) -> dict[str, object]:
    target_by_decision = {
        "TOOL_ROUTE": "tool_route",
        "RETRIEVAL": "context_retriever",
        "PLANNING": "planning",
        "REVIEW": "review",
        "DOMAIN_VALIDATION": "domain_validation",
        "RESPONSE_SYNTHESIS": "response_synthesis",
        "WAITING_CONFIRMATION": "waiting_confirmation",
        "BLOCK_RUN": "block_run",
        "DOMAIN_RECONCILE": "domain_reconcile",
        "RECOVERY": "recovery",
        "FINALIZE": "finalize",
    }
    target = target_by_decision[decision["target"]]
    if decision["target"] == "RETRIEVAL":
        patch.update(
            {
                "work_analysis_result": None,
                "planning_result": None,
                "plan_review_result": None,
                "__v2_revision_mode__": None,
            }
        )
    elif decision["target"] == "TOOL_ROUTE":
        patch.update(
            {
                "acquisition_result": None,
                "retrieval_result": None,
                "context_result": None,
                "source_fetch_plans": [],
                "work_analysis_result": None,
                "planning_result": None,
                "plan_review_result": None,
                "__v2_revision_mode__": None,
            }
        )
    elif decision["target"] == "REVIEW":
        patch["plan_review_result"] = None
    patch["__target__"] = target
    patch["__logical_target__"] = target
    return patch


def _work_analysis_meta(
    state: ProductionGraphStateV2,
    *,
    artifact_id: str,
    policy_confirmation_receipt_refs: list[StateArtifactRefV1],
) -> StateArtifactMetaV1:
    request_intent = cast(
        RequestIntentV2,
        _required_mapping_value(state.get("request_intent"), "request_intent"),
    )
    tool_route_plan = cast(
        ToolRoutePlanV2,
        _required_mapping_value(state.get("tool_route_plan"), "tool_route_plan"),
    )
    retrieval_result = cast(
        RetrievalResultV1,
        _required_mapping_value(state.get("retrieval_result"), "retrieval_result"),
    )
    based_on = _ordered_unique_artifact_refs(
        [
            cast(StateArtifactRefV1, _artifact_ref(request_intent["meta"])),
            cast(
                StateArtifactRefV1,
                _artifact_ref(tool_route_plan["output_plan"]["meta"]),
            ),
            cast(StateArtifactRefV1, _artifact_ref(retrieval_result["meta"])),
            *policy_confirmation_receipt_refs,
        ]
    )
    return {
        "artifact_id": _required_text(artifact_id, "work analysis artifact id"),
        "revision": 1,
        "based_on": based_on,
    }


def _validated_work_analysis_receipt_refs(
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1],
) -> list[StateArtifactRefV1]:
    """Fail closed until exact Policy Receipt provenance is production authority.

    The current branch can observe receipt DTOs and downstream DV can check that
    a referenced receipt exists and is APPROVED, but it cannot prove the exact
    active ``decision_context_hash`` plus current target/scope binding required
    by IMP-200~209. Therefore no receipt, including an APPROVED receipt, is
    promoted to Work Analysis authorization in R1.1. DECLINED, malformed,
    stale, wrong-context and wrong-scope receipts consequently also authorize
    nothing. The input is intentionally consumed only at this deterministic
    boundary so ``policy_confirmation_receipt_refs`` and ``meta.based_on``
    cannot drift through independent filtering.
    """

    if not isinstance(policy_confirmation_receipts, list):
        raise ProductionV2RuntimeBindingError(
            "policy confirmation receipt projection requires a list"
        )
    return []


def _ordered_unique_artifact_refs(
    refs: list[StateArtifactRefV1],
) -> list[StateArtifactRefV1]:
    result: list[StateArtifactRefV1] = []
    seen: set[tuple[str, int]] = set()
    for raw in refs:
        ref = cast(StateArtifactRefV1, _artifact_ref(raw))
        key = (ref["artifact_id"], ref["revision"])
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _artifact_ref(meta: Mapping[str, object]) -> dict[str, object]:
    artifact_id = _required_text(meta.get("artifact_id"), "artifact meta id")
    revision = meta.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ProductionV2RuntimeBindingError("artifact meta revision is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _request(state: ProductionGraphStateV2) -> WorkflowStartRequest:
    request = state.get("__request__")
    if not isinstance(request, WorkflowStartRequest):
        raise ProductionV2RuntimeBindingError(
            "Production V2 state is missing WorkflowStartRequest"
        )
    return request


def _required_mapping_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProductionV2RuntimeBindingError(
            f"Production V2 state is missing {label}"
        )
    return cast(Mapping[str, object], value)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProductionV2RuntimeBindingError(f"{label} is required")
    return value


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
    actual = [item["evidence_id"] for item in evidence]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ProductionV2RuntimeBindingError(
            "current-run Evidence does not match RetrievalResultV1"
        )
    by_id = {item["evidence_id"]: item for item in evidence}
    return [by_id[evidence_id] for evidence_id in expected]


def _policy_receipts(
    state: ProductionGraphStateV2,
) -> list[PolicyConfirmationReceiptV1]:
    raw = state.get("policy_confirmation_receipts", [])
    if not isinstance(raw, list):
        raise ProductionV2RuntimeBindingError(
            "policy_confirmation_receipts must be a list"
        )
    return cast(list[PolicyConfirmationReceiptV1], raw)


def _retry_budget(state: ProductionGraphStateV2) -> RunBudgetV1:
    value = state.get("retry_budget")
    if not isinstance(value, Mapping):
        raise ProductionV2RuntimeBindingError("retry_budget is required")
    return cast(RunBudgetV1, value)


def _action_plan(value: object, *, label: str) -> ActionPlanDraftV2:
    root = _required_mapping_value(value, "planning_result")
    if "answer" in root:
        raise ProductionV2RuntimeBindingError(
            f"{label} requires ActionPlanDraftV2; ANSWER_ONLY cannot enter Review/DV"
        )
    if root.get("schema_version") != 2 or not isinstance(root.get("actions"), list):
        raise ProductionV2RuntimeBindingError(
            f"{label} requires ActionPlanDraftV2"
        )
    return cast(ActionPlanDraftV2, root)


def _review_result(
    value: object,
    *,
    required_status: str,
) -> PlanReviewResultV2:
    root = _required_mapping_value(value, "plan_review_result")
    if root.get("schema_version") != 2 or root.get("status") != required_status:
        raise ProductionV2RuntimeBindingError(
            f"PlanReviewResultV2 status must be {required_status}"
        )
    return cast(PlanReviewResultV2, root)


def _looks_like_work_analysis_result(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema_version") == 2
        and "work_facts" in value
        and "action_necessity" in value
    )


def _confirmation_context(
    state: ProductionGraphStateV2,
    *,
    owner: str,
    resolver: ConfirmationContextResolver,
) -> tuple[str, RegisteredResumeTargetRefV1] | None:
    context = resolver(state, owner)
    if context is None:
        return None
    interrupt_id, resume_target = context
    _required_text(interrupt_id, "interrupt_id")
    if resume_target.get("subgraph_id") != owner:
        raise ProductionV2RuntimeBindingError(
            "confirmation resume target must match the originating owner"
        )
    return interrupt_id, resume_target


__all__ = [
    "ProductionV2RuntimeBindingError",
    "ProductionV2RuntimeDependencies",
    "ProductionV2RuntimeHandlers",
    "apply_v2_router_reentry",
]
