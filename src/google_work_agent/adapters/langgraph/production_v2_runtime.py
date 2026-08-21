"""Bounded SIX_ROLE production V2 node handlers and deterministic state handoff.

This module binds the already-built Runtime V2 application producers to the
post-Retrieval LangGraph state without activating the final product graph.
It intentionally leaves ``adapters.langgraph.__init__`` and InvocationCoordinator
unchanged for Runtime R2/R3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from google_work_agent.adapters.langgraph.production_v2_graph import (
    ProductionGraphStateV2,
)
from google_work_agent.application.workflows.contracts import (
    DomainValidationOutputV1,
    PolicyConfirmationReceiptV1,
    RunBudgetV1,
)
from google_work_agent.application.workflows.domain_validation_v2 import (
    RunScopedResourceIdentityReader,
)
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalResultV1,
    StateArtifactMetaV1,
    SubgraphReturnV2,
    WorkflowSignalV1,
)
from google_work_agent.application.workflows.planning_plan_assembler import (
    ActionPlanDraftV2,
)
from google_work_agent.application.workflows.planning_revision_v2 import (
    PlanningV2RevisionProducer,
)
from google_work_agent.application.workflows.planning_runtime_v2 import (
    PlanningV2Producer,
)
from google_work_agent.application.workflows.post_retrieval_envelopes_v2 import (
    PlanningResultV2,
    validate_work_analysis_return_v2,
)
from google_work_agent.application.workflows.post_retrieval_runtime_v2 import (
    PostRetrievalRuntimeV2Boundary,
)
from google_work_agent.application.workflows.post_retrieval_supervisor_v2 import (
    BlockRunExecutor,
    PostRetrievalRouteDecisionV2,
    RevisionBudgetBlockContextV1,
    route_planning_return_v2,
    route_review_return_v2,
    route_work_analysis_return_v2,
)
from google_work_agent.application.workflows.review_runtime_v2 import ReviewV2Producer
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.application.workflows.work_analysis_v2 import (
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
        # every invocation.  No resolver survives in graph/checkpoint state.
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
        result = chain.run(
            user_request=request.request_text,
            request_intent=cast(RequestIntentV2, request_intent),
            retrieval_result=retrieval_result,
            evidence_drafts=evidence,
            meta=_work_analysis_meta(
                state,
                artifact_id=self._deps.artifact_id_factory(
                    "work_analysis",
                    request.run_id,
                ),
            ),
            policy_confirmation_receipt_refs=[
                cast(PolicyConfirmationReceiptV1, receipt)["meta"]
                for receipt in _policy_receipts(state)
            ],
            confirmation_response=_owner_confirmation_response(
                state,
                owner="WORK_ANALYSIS",
            ),
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
        # Runtime V2 DV receives ActionPlanDraftV2 only.  Treat an ALLOW_READ
        # result as a durable-state reconciliation case, never as success.
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
    return {
        "artifact_id": _required_text(artifact_id, "work analysis artifact id"),
        "revision": 1,
        "based_on": [
            _artifact_ref(request_intent["meta"]),
            _artifact_ref(tool_route_plan["input_plan"]["meta"]),
            _artifact_ref(retrieval_result["meta"]),
        ],
    }


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


def _owner_confirmation_response(
    state: ProductionGraphStateV2,
    *,
    owner: str,
) -> Mapping[str, object] | None:
    prompt_context = state.get("prompt_context")
    if not isinstance(prompt_context, Mapping):
        return None
    if prompt_context.get("confirmation_owner_subgraph") != owner:
        return None
    response = prompt_context.get("confirmation_response")
    if response is None:
        return None
    if not isinstance(response, Mapping):
        raise ProductionV2RuntimeBindingError(
            "confirmation_response must be a bounded mapping"
        )
    return cast(Mapping[str, object], response)


__all__ = [
    "ProductionV2RuntimeBindingError",
    "ProductionV2RuntimeDependencies",
    "ProductionV2RuntimeHandlers",
    "apply_v2_router_reentry",
]
