"""Deterministic supervisor routing over frozen workflow contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import StrEnum
from typing import TypedDict, cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    ReviewBlockV2,
    ReviewConfirmV2,
    ReviewRetrieveMoreV2,
    ReviewReviseV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRouteDisposition,
    ToolRouteResultV1,
)
from google_work_agent.application.orchestration.api_acquisition import (
    build_source_planning_clarification_question,
)
from google_work_agent.application.orchestration.confirmation import (
    build_user_interrupt_v1,
    validate_clarification_question_v1,
)
from google_work_agent.application.orchestration.contracts import (
    AdditionalAcquisitionRequestV1,
    BudgetDecision,
    BudgetDecisionV1,
    BudgetProfile,
    DomainValidationOutputV1,
    DomainValidationResult,
    FinalizeIntent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanningResult,
    RequestUnderstandingResult,
    ReviewResult,
    RunBudgetV1,
    WorkflowPhase,
    approve_additional_acquisition,
    approve_planning_revision,
    approve_review_recheck,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
    promote_budget_profile,
    validate_finalize_intent_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ClarificationQuestionV1,
    RequestIntentV2,
    RequestUnderstandingOutputV1,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RetrievalResultV1,
    RouteReconsiderationRequiredV1,
    SourcePlanningOutputV1,
)
from google_work_agent.application.orchestration.insufficient_data import (
    InsufficientDataContext,
    InsufficientDataDisposition,
    InsufficientDataIssue,
    ResolutionSource,
    decide_insufficient_data,
)
from google_work_agent.application.orchestration.solution_planning import (
    build_solution_planning_clarification_question,
)

JsonObject = dict[str, object]


class SupervisorTarget(StrEnum):
    """Deterministic routing targets selected by the Stage 10 supervisor."""

    TOOL_ROUTE = "TOOL_ROUTE"
    SOURCE_PLANNING = "SOURCE_PLANNING"
    API_ACQUISITION = "API_ACQUISITION"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    WORK_ANALYSIS = "WORK_ANALYSIS"
    SOLUTION_PLANNING = "SOLUTION_PLANNING"
    PLAN_REVIEW_INSPECT = "PLAN_REVIEW_INSPECT"
    PLAN_REVIEW_RECHECK = "PLAN_REVIEW_RECHECK"
    PLANNING_REVISE_ANSWER = "PLANNING_REVISE_ANSWER"
    PLANNING_REVISE_PLAN = "PLANNING_REVISE_PLAN"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREFLIGHT = "PREFLIGHT"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FINALIZE = "FINALIZE"
    REAUTH = "REAUTH"
    RECOVERY = "RECOVERY"


class SupervisorDecisionV1(TypedDict):
    """Minimal deterministic routing result returned by the supervisor."""

    target: str
    next_phase: str | None
    state_update: GraphStateUpdateV1
    reason_code: str | None
    budget_decision: BudgetDecisionV1 | None


class RetrievalRouteResultV1(TypedDict):
    """Retrieval's own SubgraphReturnV2-shaped routing input (Q2-HANDOFF).

    ``disposition`` is Retrieval's guard-corrected sufficiency status; when
    it is SUFFICIENT/PARTIAL, ``typed_result`` carries the canonical,
    already-materialized ``RetrievalResultV1`` and is the sole authority for
    the WORK_ANALYSIS handoff. Retrieval's own local loop never sets a
    signal here -- ``RetrievalRequiredV1`` is only ever constructed by
    Supervisor itself, for the Work Analysis/Review edges."""

    disposition: str
    typed_result: RetrievalResultV1 | None


def route_supervisor(
    *,
    phase: WorkflowPhase | str,
    state: MultiAgentGraphState,
    result: object | None = None,
) -> SupervisorDecisionV1:
    current_phase = WorkflowPhase(phase)
    if current_phase is WorkflowPhase.WORK_ANALYSIS:
        raise ValueError("Work Analysis routing is owned by its canonical eight-node subgraph")
    reconsideration = _route_reconsideration(current_phase, result)
    if reconsideration is not None:
        return reconsideration
    if current_phase is WorkflowPhase.REQUEST_ANALYSIS:
        return _route_request_understanding(
            state=state,
            output=cast(RequestUnderstandingOutputV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.TOOL_ROUTING:
        return _route_tool_routing(
            state=state,
            result=cast(ToolRouteResultV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.SOURCE_PLANNING:
        return _route_source_planning(
            state=state,
            output=cast(SourcePlanningOutputV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.API_ACQUISITION:
        return _route_api_acquisition(
            state=state, result=cast(AcquisitionResultV1, _require_mapping(result, "result"))
        )
    if current_phase in {
        WorkflowPhase.CONTEXT_RETRIEVAL,
        WorkflowPhase.CONTEXT_EVALUATION,
    }:
        return _route_retrieval(
            state=state,
            retrieval_return=cast(RetrievalRouteResultV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.SOLUTION_PLANNING:
        return _route_solution_planning(
            state=state,
            result=cast(
                AnswerDraftV1 | ActionPlanDraftV1,
                _require_mapping(result, "result"),
            ),
        )
    if current_phase is WorkflowPhase.PLAN_REVIEW:
        return _route_plan_review(
            state=state,
            result=cast(PlanReviewResultV2, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.DOMAIN_VALIDATION:
        return _route_domain_validation(
            state=state,
            result=cast(DomainValidationOutputV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.PREFLIGHT:
        return _route_preflight(
            state=state,
            result=_claim_result_mapping(result, "result"),
        )
    if current_phase is WorkflowPhase.RECOVERY:
        return _decision(
            target=SupervisorTarget.RECOVERY,
            next_phase=WorkflowPhase.RECOVERY,
            state_update=_base_state_update(WorkflowPhase.RECOVERY),
            reason_code="RECOVERY_REQUIRED",
        )
    if current_phase is WorkflowPhase.FINALIZE:
        return _decision(
            target=SupervisorTarget.FINALIZE,
            next_phase=WorkflowPhase.FINALIZE,
            state_update=_base_state_update(WorkflowPhase.FINALIZE),
            reason_code="FINALIZE_READY",
        )
    raise ValueError(f"unsupported supervisor phase: {current_phase.value}")


def _route_reconsideration(
    phase: WorkflowPhase,
    result: object | None,
) -> SupervisorDecisionV1 | None:
    if not isinstance(result, Mapping):
        return None
    status = result.get("disposition", result.get("status", result.get("result")))
    expected = {
        WorkflowPhase.CONTEXT_RETRIEVAL: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.CONTEXT_EVALUATION: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.WORK_ANALYSIS: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.SOLUTION_PLANNING: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.PLAN_REVIEW: "ROUTE_RECONSIDERATION",
    }.get(phase)
    if expected is None or status != expected:
        return None
    raw_reason_codes = result.get("reason_codes", [])
    if phase is WorkflowPhase.PLAN_REVIEW:
        route_issues = result.get("route_issues", [])
        raw_reason_codes = (
            [
                item["code"]
                for item in route_issues
                if isinstance(item, Mapping) and isinstance(item.get("code"), str)
            ]
            if isinstance(route_issues, list)
            else []
        )
    reason_codes = (
        [item for item in raw_reason_codes if isinstance(item, str)]
        if isinstance(raw_reason_codes, list)
        else []
    )
    signal: RouteReconsiderationRequiredV1 = {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": reason_codes or ["ROUTE_RECONSIDERATION_REQUIRED"],
    }
    review_update = (
        {"plan_review": cast(PlanReviewResultV2, result)}
        if phase is WorkflowPhase.PLAN_REVIEW
        else {"plan_review": None}
    )
    return _decision(
        target=SupervisorTarget.TOOL_ROUTE,
        next_phase=WorkflowPhase.TOOL_ROUTING,
        state_update=_base_state_update(
            WorkflowPhase.TOOL_ROUTING,
            workflow_signal=signal,
            source_fetch_plans=[],
            acquisition_result=None,
            context_result=None,
            work_analysis_result=None,
            answer_draft=None,
            plan_draft=None,
            **review_update,
        ),
        reason_code=signal["reason_codes"][0],
    )


def _route_request_understanding(
    *,
    state: MultiAgentGraphState,
    output: RequestUnderstandingOutputV1,
) -> SupervisorDecisionV1:
    result = RequestUnderstandingResult(output["result"])
    request_intent = output.get("request_intent")
    if result is RequestUnderstandingResult.COMPLETE:
        return _decision(
            target=SupervisorTarget.TOOL_ROUTE,
            next_phase=WorkflowPhase.TOOL_ROUTING,
            state_update=_base_state_update(
                WorkflowPhase.TOOL_ROUTING,
                request_intent=request_intent,
            ),
        )
    if result is RequestUnderstandingResult.NEEDS_CONFIRMATION:
        question = validate_clarification_question_v1(output["clarification"])
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                request_intent=request_intent,
            ),
            reason_code=question["reason_code"],
        )
    reason_code = _request_invalid_reason_code(output)
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=reason_code,
        request_intent=request_intent,
    )


def _route_tool_routing(
    *,
    state: MultiAgentGraphState,
    result: ToolRouteResultV1,
) -> SupervisorDecisionV1:
    try:
        disposition = ToolRouteDisposition(result["disposition"])
    except (KeyError, ValueError):
        return _decision(
            target=SupervisorTarget.RECOVERY,
            next_phase=WorkflowPhase.RECOVERY,
            state_update=_base_state_update(
                WorkflowPhase.RECOVERY,
                execution_summary={"result": "CONTRACT_VIOLATION"},
            ),
            reason_code="TOOL_ROUTE_CONTRACT_VIOLATION",
        )
    plan = result["tool_route_plan"]
    if disposition in {
        ToolRouteDisposition.ROUTE_READY,
        ToolRouteDisposition.NO_TOOL_NEEDED,
    }:
        if plan is None:
            return _decision(
                target=SupervisorTarget.RECOVERY,
                next_phase=WorkflowPhase.RECOVERY,
                state_update=_base_state_update(
                    WorkflowPhase.RECOVERY,
                    execution_summary={"result": "CONTRACT_VIOLATION"},
                ),
                reason_code="TOOL_ROUTE_PLAN_MISSING",
            )
        return _decision(
            target=SupervisorTarget.CONTEXT_RETRIEVAL,
            next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state_update=_base_state_update(
                WorkflowPhase.CONTEXT_RETRIEVAL,
                tool_route_plan=plan,
                workflow_signal=None,
                retry_budget=_retrieval_route_budget(state),
            ),
            reason_code=disposition.value,
        )
    if disposition is ToolRouteDisposition.NEEDS_CONFIRMATION:
        question: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "tool_route.finalize",
            "question": "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요.",
            "affected_field_paths": [
                "requested_resource_hints",
                "requested_effect_hints",
            ],
            "reason_code": result["reason_codes"][0]
            if result["reason_codes"]
            else "TOOL_ROUTE_NEEDS_CONFIRMATION",
            "known_context_summary": _request_intent_from_state(state)["goal"],
            "options": [],
        }
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                tool_route_plan=None,
                workflow_signal=result["workflow_signal"],
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=result["reason_codes"][0] if result["reason_codes"] else "TOOL_ROUTE_BLOCKED",
        tool_route_plan=None,
        workflow_signal=result["workflow_signal"],
    )


def _route_source_planning(
    *,
    state: MultiAgentGraphState,
    output: SourcePlanningOutputV1,
) -> SupervisorDecisionV1:
    result = str(output["result"])
    source_fetch_plans = list(output["source_fetch_plans"])
    if result == "PLAN_READY":
        return _decision(
            target=SupervisorTarget.API_ACQUISITION,
            next_phase=WorkflowPhase.API_ACQUISITION,
            state_update=_base_state_update(
                WorkflowPhase.API_ACQUISITION,
                source_fetch_plans=source_fetch_plans,
            ),
            reason_code=result,
        )
    if result == "NO_FETCH_NEEDED":
        return _decision(
            target=SupervisorTarget.CONTEXT_RETRIEVAL,
            next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state_update=_base_state_update(
                WorkflowPhase.CONTEXT_RETRIEVAL,
                source_fetch_plans=source_fetch_plans,
                acquisition_result=_build_no_fetch_acquisition_result(),
            ),
            reason_code=result,
        )
    if result == "NEEDS_CONFIRMATION":
        question = build_source_planning_clarification_question(
            output=output,
            request_intent=_request_intent_from_state(state),
        )
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                source_fetch_plans=source_fetch_plans,
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=_reason_from_failure_mapping(
            output.get("failure"), default="SOURCE_PLANNING_BLOCKED"
        ),
        source_fetch_plans=source_fetch_plans,
    )


def _retrieval_route_budget(state: MultiAgentGraphState) -> RunBudgetV1:
    budget = dict(state["retry_budget"])
    budget["profile"] = promote_budget_profile(
        budget["profile"], BudgetProfile.RETRIEVAL_HEAVY
    ).value
    return cast(RunBudgetV1, budget)


def _route_api_acquisition(
    *,
    state: MultiAgentGraphState,
    result: AcquisitionResultV1,
) -> SupervisorDecisionV1:
    status = str(result["status"])
    if status in {"COMPLETE", "PARTIAL", "RATE_LIMITED", "BUDGET_EXHAUSTED"}:
        return _decision(
            target=SupervisorTarget.CONTEXT_RETRIEVAL,
            next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state_update=_base_state_update(
                WorkflowPhase.CONTEXT_RETRIEVAL,
                acquisition_result=result,
            ),
            reason_code=status,
        )
    if status == "AUTH_REQUIRED":
        return _decision(
            target=SupervisorTarget.REAUTH,
            next_phase=None,
            state_update=_boundary_state_update(acquisition_result=result),
            reason_code="AUTH_REQUIRED",
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.FAILED.value,
        reason_code="API_ACQUISITION_FAILED",
        acquisition_result=result,
    )


def _route_retrieval(
    *,
    state: MultiAgentGraphState,
    retrieval_return: RetrievalRouteResultV1,
) -> SupervisorDecisionV1:
    """Route only the canonical Retrieval return artifact/disposition."""
    disposition = retrieval_return["disposition"]
    retrieval_result = retrieval_return["typed_result"]
    if disposition in {"SUFFICIENT", "PARTIAL"}:
        # A frozen tool_route_plan is required to materialize RetrievalResultV1
        # (Q2-HANDOFF coverage gating); compatibility fixtures without one
        # still route on disposition alone, same as before this migration --
        # they simply have no canonical artifact to attach.
        work_analysis_update: GraphStateUpdateV1 = {}
        if retrieval_result is not None:
            work_analysis_update["retrieval_result"] = retrieval_result
        return _decision(
            target=SupervisorTarget.WORK_ANALYSIS,
            next_phase=WorkflowPhase.WORK_ANALYSIS,
            state_update=_base_state_update(
                WorkflowPhase.WORK_ANALYSIS,
                current_update=work_analysis_update,
            ),
            reason_code=disposition,
        )
    if disposition == "NEEDS_MORE_DATA":
        raise ValueError("Retrieval NEEDS_MORE_DATA must remain inside its bounded local loop")
    if disposition == "NEEDS_CONFIRMATION":
        raise ValueError("Retrieval confirmation must be handled at its owner checkpoint")
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code="CONTEXT_BLOCKED",
    )


def _route_retrieval_required(
    *,
    state: MultiAgentGraphState,
    reason_code: str,
    current_update: GraphStateUpdateV1,
    request: AdditionalAcquisitionRequestV1 | None,
) -> SupervisorDecisionV1:
    """WorkAnalysis NEEDS_MORE_DATA / Review RETRIEVE_MORE -> Retrieval, almost always.

    NEEDS_MORE_DATA/RETRIEVE_MORE is *itself* the "same fixed route, more
    evidence" disposition (06-agent-workflow.md SS3 -- distinct from the
    official ``ROUTE_RECONSIDERATION_REQUIRED``/``ROUTE_RECONSIDERATION``
    disposition, which ``_route_reconsideration`` already intercepts at the
    top of ``route_supervisor`` *before* ``_route_analysis``/``_route_plan_review``
    ever call this function). This function is therefore never the place
    that decides "a new Resource/Connector/Route is needed" -- that
    decision belongs solely to the official reconsideration disposition.

    What this function *does* do, after reusing the same budget/PARTIAL-fallback
    guard ``_route_additional_acquisition`` uses: check whether a frozen IN
    Route actually exists to retry the (by-definition same-route) request
    within. This is a pure **executability guard**, not a route-adequacy
    judgment -- ``missing_information`` strings are never interpreted to infer
    whether the current route can serve them. If the guard passes,
    ``RetrievalRequiredV1`` re-enters Retrieval. If the guard fails (no frozen
    input route exists to retry within, which should not normally happen for
    a same-route disposition), this falls back to Tool Route as a fail-closed
    recovery -- tagged with a distinct guard-failure reason code so it is
    never mistaken for an official reconsideration signal in traces/logs.
    Retrieval's own local-loop NEEDS_MORE_DATA never reaches this function --
    it stays inside the Retrieval subgraph.
    """
    if request is None:
        raise ValueError("retrieval-required route requires a structured acquisition request")
    budget = approve_additional_acquisition(state["retry_budget"])
    disposition = decide_insufficient_data(
        InsufficientDataContext(
            issues=(
                InsufficientDataIssue(
                    issue_type=reason_code,
                    required=True,
                    resolution_source=ResolutionSource.GOOGLE,
                ),
            ),
            budget_remaining=1 if budget["decision"] == BudgetDecision.ALLOW.value else 0,
            read_only=state.get("requested_effect_type") == "READ",
            evidence_supported_partial_possible=_has_supported_evidence(current_update),
            write_required_data_missing=state.get("requested_effect_type") != "READ",
        )
    )
    if disposition is InsufficientDataDisposition.PARTIAL:
        return _finalize(
            state=state,
            intent=FinalizeIntent.COMPLETED.value,
            reason_code="EVIDENCE_SUPPORTED_PARTIAL",
            result_kind="PARTIAL",
            budget_decision=budget,
            current_update=current_update,
        )
    if budget["decision"] == BudgetDecision.DENY.value:
        return _finalize(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=_budget_reason_code(budget, default=reason_code),
            budget_decision=budget,
            current_update=current_update,
        )
    reason_codes = list(request["reason_codes"]) or [reason_code]
    tool_route_plan = state.get("tool_route_plan")
    # Pure executability guard: NEEDS_MORE_DATA/RETRIEVE_MORE is definitionally
    # "same route" already -- this only checks whether a route to retry within
    # actually exists, never whether the route is the *right* one.
    has_frozen_input_route = bool(
        tool_route_plan is not None and tool_route_plan["input_plan"]["input_routes"]
    )
    if not has_frozen_input_route:
        # Fail-closed fallback, not an official ROUTE_RECONSIDERATION_REQUIRED
        # signal -- the leading reason code marks the guard failure so it is
        # distinguishable from a genuine reconsideration disposition (that
        # channel is _route_reconsideration, above).
        guard_reason_codes = ["RETRIEVAL_INPUT_ROUTE_UNAVAILABLE", *reason_codes]
        route_signal: RouteReconsiderationRequiredV1 = {
            "kind": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": guard_reason_codes,
        }
        return _decision(
            target=SupervisorTarget.TOOL_ROUTE,
            next_phase=WorkflowPhase.TOOL_ROUTING,
            state_update=_base_state_update(
                WorkflowPhase.TOOL_ROUTING,
                retry_budget=budget["run_budget"],
                current_update=current_update,
                workflow_signal=route_signal,
            ),
            reason_code=guard_reason_codes[0],
            budget_decision=budget,
        )
    needs: list[RetrievalNeedV1] = [
        {"required_information": info, "reason_codes": reason_codes}
        for info in request["missing_information"]
    ] or [{"required_information": reason_code, "reason_codes": reason_codes}]
    retrieval_signal: RetrievalRequiredV1 = {
        "kind": "RETRIEVAL_REQUIRED",
        "reason_codes": reason_codes,
        "needs": needs,
    }
    return _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL,
        next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
        state_update=_base_state_update(
            WorkflowPhase.CONTEXT_RETRIEVAL,
            retry_budget=budget["run_budget"],
            current_update=current_update,
            workflow_signal=retrieval_signal,
        ),
        reason_code=reason_codes[0],
        budget_decision=budget,
    )


def _route_solution_planning(
    *,
    state: MultiAgentGraphState,
    result: AnswerDraftV1 | ActionPlanDraftV1,
) -> SupervisorDecisionV1:
    status = PlanningResult(str(result["status"]))
    planning_update = _planning_state_update(result)
    if status in {PlanningResult.ANSWER_ONLY, PlanningResult.PLAN_READY}:
        if _is_revision_follow_up(state):
            return _route_review_recheck(
                state=state,
                current_update=planning_update,
            )
        return _decision(
            target=SupervisorTarget.PLAN_REVIEW_INSPECT,
            next_phase=WorkflowPhase.PLAN_REVIEW,
            state_update=_base_state_update(
                WorkflowPhase.PLAN_REVIEW,
                current_update=planning_update,
            ),
            reason_code=status.value,
        )
    if status is PlanningResult.NEEDS_CONFIRMATION:
        question = build_solution_planning_clarification_question(
            result=result,
            request_intent=_request_intent_from_state(state),
        )
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                **planning_update,
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=_planning_block_reason_code(result),
        current_update=planning_update,
    )


def _route_plan_review(
    *,
    state: MultiAgentGraphState,
    result: PlanReviewResultV2,
) -> SupervisorDecisionV1:
    status = ReviewResult(str(result["status"]))
    review_update: GraphStateUpdateV1 = {"plan_review": result}
    if status is ReviewResult.PASS:
        target_kind = _review_target_from_state(state)
        if target_kind == "ANSWER":
            return _finalize(
                state=state,
                intent=FinalizeIntent.COMPLETED.value,
                reason_code="ANSWER_ONLY_REVIEW_PASS",
                current_update=review_update,
            )
        return _decision(
            target=SupervisorTarget.DOMAIN_VALIDATION,
            next_phase=WorkflowPhase.DOMAIN_VALIDATION,
            state_update=_base_state_update(
                WorkflowPhase.DOMAIN_VALIDATION,
                current_update=review_update,
            ),
            reason_code="PLAN_REVIEW_PASS",
        )
    if status is ReviewResult.REVISE:
        revised_result = cast(ReviewReviseV2, result)
        revision_budget = approve_planning_revision(state["retry_budget"])
        if revision_budget["decision"] == BudgetDecision.DENY.value:
            return _finalize(
                state=state,
                intent=FinalizeIntent.BLOCKED.value,
                reason_code=_budget_reason_code(
                    revision_budget, default="PLANNING_REVISION_DENIED"
                ),
                budget_decision=revision_budget,
                current_update=review_update,
            )
        target_kind = _review_target_from_state(state)
        # Semantic Revision dedup (docs/06 SS10.1, contracts.approve_semantic_revision):
        # same target Planning node + same normalized Review failure signature
        # gets at most one revision attempt per Run, persisted in
        # retry_budget.semantic_revision_signatures_used so it survives
        # resume/re-entry/checkpoint restore. Only gated when Review actually
        # reported a failure signature to dedup against -- an issue-free
        # REVISE has nothing to record and falls back to the planning-revision
        # cap alone.
        node_id = "planning.revise_answer" if target_kind == "ANSWER" else "planning.revise_plan"
        failure_reason_codes = [issue["code"] for issue in revised_result["issues"]]
        if failure_reason_codes:
            signature = build_semantic_failure_signature_v1(
                node_id=node_id,
                failure_reason_codes=failure_reason_codes,
            )
            budget = approve_semantic_revision(revision_budget["run_budget"], signature=signature)
            if budget["decision"] == BudgetDecision.DENY.value:
                return _finalize(
                    state=state,
                    intent=FinalizeIntent.BLOCKED.value,
                    reason_code=_budget_reason_code(budget, default="SEMANTIC_REVISION_DENIED"),
                    budget_decision=budget,
                    current_update=review_update,
                )
        else:
            budget = revision_budget
        target = (
            SupervisorTarget.PLANNING_REVISE_ANSWER
            if target_kind == "ANSWER"
            else SupervisorTarget.PLANNING_REVISE_PLAN
        )
        return _decision(
            target=target,
            next_phase=WorkflowPhase.SOLUTION_PLANNING,
            state_update=_base_state_update(
                WorkflowPhase.SOLUTION_PLANNING,
                retry_budget=budget["run_budget"],
                current_update=review_update,
            ),
            reason_code="PLAN_REVIEW_REVISE",
            budget_decision=budget,
        )
    if status is ReviewResult.RETRIEVE_MORE:
        retrieval_result = cast(ReviewRetrieveMoreV2, result)
        reason_codes = list(dict.fromkeys(gap["code"] for gap in retrieval_result["evidence_gaps"]))
        missing_information = [
            information
            for gap in retrieval_result["evidence_gaps"]
            for information in gap["required_information"]
        ]
        return _route_retrieval_required(
            state=state,
            reason_code="PLAN_REVIEW_RETRIEVE_MORE",
            current_update=review_update,
            request={
                "schema_version": 1,
                "origin_phase": WorkflowPhase.PLAN_REVIEW.value,
                "origin_result": ReviewResult.RETRIEVE_MORE.value,
                "missing_slots": [],
                "missing_information": list(dict.fromkeys(missing_information)),
                "evidence_refs": [],
                "reason_codes": reason_codes,
            },
        )
    if status is ReviewResult.CONFIRM:
        confirmation = cast(ReviewConfirmV2, result)["confirmation"]
        question: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "review.aggregate_findings",
            "question": confirmation["question"],
            "affected_field_paths": [],
            "reason_code": "PLAN_REVIEW_CONFIRM",
            "known_context_summary": str(
                _request_intent_from_state(state).get("goal", "Plan review")
            ),
            "options": [
                {"option_id": option, "label": option} for option in confirmation["options"]
            ],
        }
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                **review_update,
            ),
            reason_code=question["reason_code"],
        )
    blocked_result = cast(ReviewBlockV2, result)
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=blocked_result["blockers"][0]["code"],
        current_update=review_update,
    )


def _route_domain_validation(
    *,
    state: MultiAgentGraphState,
    result: DomainValidationOutputV1,
) -> SupervisorDecisionV1:
    validation_result = DomainValidationResult(str(result["result"]))
    if validation_result is DomainValidationResult.ALLOW_READ:
        return _decision(
            target=SupervisorTarget.PREFLIGHT,
            next_phase=WorkflowPhase.PREFLIGHT,
            state_update=_base_state_update(WorkflowPhase.PREFLIGHT),
            reason_code=_domain_validation_reason_code(result, default="ALLOW_READ"),
        )
    if validation_result is DomainValidationResult.REQUIRE_APPROVAL:
        return _decision(
            target=SupervisorTarget.WAITING_APPROVAL,
            next_phase=WorkflowPhase.WAITING_APPROVAL,
            state_update=_base_state_update(WorkflowPhase.WAITING_APPROVAL),
            reason_code=_domain_validation_reason_code(result, default="REQUIRE_APPROVAL"),
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=_domain_validation_reason_code(result, default="DOMAIN_VALIDATION_BLOCKED"),
        plan_draft=state.get("plan_draft"),
        plan_review=state.get("plan_review"),
        work_analysis_result=state.get("work_analysis_result"),
    )


def _route_preflight(
    *,
    state: MultiAgentGraphState,
    result: JsonObject,
) -> SupervisorDecisionV1:
    result_code = _preflight_result_code(result, default="PREFLIGHT_REJECTED")
    safe_error_code = _preflight_safe_error_code(result)
    if safe_error_code == "REAUTH_REQUIRED" or result_code == "REAUTH_REQUIRED":
        return _decision(
            target=SupervisorTarget.REAUTH,
            next_phase=None,
            state_update=_boundary_state_update(),
            reason_code="REAUTH_REQUIRED",
        )
    if bool(result.get("applied")):
        return _decision(
            target=SupervisorTarget.ACTION_EXECUTION,
            next_phase=WorkflowPhase.ACTION_EXECUTION,
            state_update=_base_state_update(WorkflowPhase.ACTION_EXECUTION),
            reason_code=result_code,
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=result_code,
    )


def _route_additional_acquisition(
    *,
    state: MultiAgentGraphState,
    reason_code: str,
    current_update: GraphStateUpdateV1,
    request: object,
) -> SupervisorDecisionV1:
    if request is None:
        raise ValueError("additional acquisition route requires a structured request")
    budget = approve_additional_acquisition(state["retry_budget"])
    disposition = decide_insufficient_data(
        InsufficientDataContext(
            issues=(
                InsufficientDataIssue(
                    issue_type=reason_code,
                    required=True,
                    resolution_source=ResolutionSource.GOOGLE,
                ),
            ),
            budget_remaining=1 if budget["decision"] == BudgetDecision.ALLOW.value else 0,
            read_only=state.get("requested_effect_type") == "READ",
            evidence_supported_partial_possible=_has_supported_evidence(current_update),
            write_required_data_missing=state.get("requested_effect_type") != "READ",
        )
    )
    if disposition is InsufficientDataDisposition.PARTIAL:
        return _finalize(
            state=state,
            intent=FinalizeIntent.COMPLETED.value,
            reason_code="EVIDENCE_SUPPORTED_PARTIAL",
            result_kind="PARTIAL",
            budget_decision=budget,
            current_update=current_update,
        )
    if budget["decision"] == BudgetDecision.DENY.value:
        return _finalize(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=_budget_reason_code(budget, default=reason_code),
            budget_decision=budget,
            current_update=current_update,
        )
    return _decision(
        target=SupervisorTarget.SOURCE_PLANNING,
        next_phase=WorkflowPhase.SOURCE_PLANNING,
        state_update=_base_state_update(
            WorkflowPhase.SOURCE_PLANNING,
            retry_budget=budget["run_budget"],
            current_update=current_update,
        ),
        reason_code=reason_code,
        budget_decision=budget,
    )


def _route_review_recheck(
    *,
    state: MultiAgentGraphState,
    current_update: GraphStateUpdateV1,
) -> SupervisorDecisionV1:
    budget = approve_review_recheck(state["retry_budget"])
    if budget["decision"] == BudgetDecision.DENY.value:
        return _finalize(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=_budget_reason_code(budget, default="REVIEW_RECHECK_DENIED"),
            budget_decision=budget,
            current_update=current_update,
        )
    return _decision(
        target=SupervisorTarget.PLAN_REVIEW_RECHECK,
        next_phase=WorkflowPhase.PLAN_REVIEW,
        state_update=_base_state_update(
            WorkflowPhase.PLAN_REVIEW,
            retry_budget=budget["run_budget"],
            current_update=current_update,
        ),
        reason_code="REVIEW_RECHECK_READY",
        budget_decision=budget,
    )


def _decision(
    *,
    target: SupervisorTarget,
    next_phase: WorkflowPhase | None,
    state_update: Mapping[str, object],
    reason_code: str | None = None,
    budget_decision: BudgetDecisionV1 | None = None,
) -> SupervisorDecisionV1:
    return {
        "target": target.value,
        "next_phase": None if next_phase is None else next_phase.value,
        "state_update": _validated_state_update(state_update),
        "reason_code": reason_code,
        "budget_decision": budget_decision,
    }


def _validated_state_update(value: Mapping[str, object]) -> GraphStateUpdateV1:
    unknown_fields = set(value).difference(GraphStateUpdateV1.__annotations__)
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"supervisor state update contains unknown fields: {names}")
    return cast(GraphStateUpdateV1, dict(value))


def _base_state_update(
    next_phase: WorkflowPhase,
    *,
    retry_budget: object | None = None,
    current_update: Mapping[str, object] | None = None,
    **extra: object,
) -> JsonObject:
    update: JsonObject = {
        "workflow_phase": next_phase.value,
        "user_interrupt": None,
        "finalize_intent": None,
    }
    if retry_budget is not None:
        update["retry_budget"] = retry_budget
    if current_update is not None:
        update.update(current_update)
    update.update(extra)
    return update


def _confirmation_state_update(
    *,
    question: ClarificationQuestionV1,
    **extra: object,
) -> JsonObject:
    update: JsonObject = {
        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
        "user_interrupt": build_user_interrupt_v1(question),
        "finalize_intent": None,
    }
    update.update(extra)
    return update


def _boundary_state_update(**extra: object) -> JsonObject:
    update: JsonObject = {
        "user_interrupt": None,
        "finalize_intent": None,
    }
    update.update(extra)
    return update


def _finalize(
    *,
    state: MultiAgentGraphState,
    intent: str,
    reason_code: str,
    result_kind: str | None = None,
    budget_decision: BudgetDecisionV1 | None = None,
    current_update: Mapping[str, object] | None = None,
    **extra: object,
) -> SupervisorDecisionV1:
    state_update = _boundary_state_update(
        **({} if current_update is None else dict(current_update)),
        **extra,
    )
    state_update.update(
        {
            "workflow_phase": WorkflowPhase.FINALIZE.value,
            "finalize_intent": validate_finalize_intent_v1(
                {
                    "schema_version": 1,
                    "intent": intent,
                    "reason_code": reason_code,
                    "result_kind": result_kind or _partial_result_kind(state, extra),
                }
            ),
        }
    )
    return _decision(
        target=SupervisorTarget.FINALIZE,
        next_phase=WorkflowPhase.FINALIZE,
        state_update=state_update,
        reason_code=reason_code,
        budget_decision=budget_decision,
    )


def _request_intent_from_state(state: MultiAgentGraphState) -> RequestIntentV2:
    # validate_request_intent_v2 is the LLM-input-only validator (meta is
    # intentionally absent from its schema -- see request_understanding.py).
    # Main State's request_intent is already a materialized RequestIntentV2
    # with meta attached, so it is trusted and cast here like every other
    # typed state payload in this module, not re-validated against the
    # narrower LLM output schema.
    return cast(RequestIntentV2, _require_mapping(state.get("request_intent"), "request_intent"))


def _review_target_from_state(
    state: MultiAgentGraphState,
) -> str:
    planning_result = cast(Mapping[str, object], state).get("planning_result")
    if isinstance(planning_result, Mapping):
        if isinstance(planning_result.get("answer"), str):
            return "ANSWER"
        if isinstance(planning_result.get("actions"), list):
            return "PLAN"
    if state.get("answer_draft") is not None:
        return "ANSWER"
    if state.get("plan_draft") is not None:
        return "PLAN"
    raise ValueError("Review requires a Planning artifact")


def _is_revision_follow_up(state: MultiAgentGraphState) -> bool:
    review = state.get("plan_review")
    return review is not None and review.get("status") == ReviewResult.REVISE.value


def _planning_state_update(
    result: AnswerDraftV1 | ActionPlanDraftV1,
) -> GraphStateUpdateV1:
    update: GraphStateUpdateV1 = {
        "answer_draft": None,
        "plan_draft": None,
    }
    if result["schema_version"] == 1:
        if PlanningResult(str(result["status"])) is PlanningResult.ANSWER_ONLY:
            update["answer_draft"] = result
        return update
    if PlanningResult(str(result["status"])) is PlanningResult.PLAN_READY:
        update["plan_draft"] = result
    return update


def _request_invalid_reason_code(output: RequestUnderstandingOutputV1) -> str:
    # RequestIntentV2 has no unsupported_scope field: Request Understanding
    # no longer judges product-capability support (Q2-X). INVALID is now
    # reserved for malformed/unusable classify output, so the only reason
    # code source is the failure record Request Understanding itself built.
    failure = _mapping_or_none(output.get("failure"))
    if (
        failure is not None
        and isinstance(failure.get("reason_code"), str)
        and failure["reason_code"]
    ):
        return cast(str, failure["reason_code"])
    return "REQUEST_UNDERSTANDING_INVALID"


def _reason_from_failure_mapping(value: object, *, default: str) -> str:
    failure = _mapping_or_none(value)
    if failure is None:
        return default
    reason_code = failure.get("reason_code")
    if isinstance(reason_code, str) and reason_code:
        return reason_code
    return default


def _planning_block_reason_code(result: AnswerDraftV1 | ActionPlanDraftV1) -> str:
    if result["schema_version"] == 1:
        reason_codes = result["reason_codes"]
        if reason_codes:
            return reason_codes[0]
        if result["blockers"]:
            return "PLANNING_BLOCKED"
    return "PLANNING_BLOCKED"


def _build_no_fetch_acquisition_result() -> AcquisitionResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": [],
        "source_summaries": [],
        "missing_slots": [],
        "remaining_budget": {
            "sources": 0,
            "pages": 0,
            "candidates": 0,
            "details": 0,
        },
    }


def _budget_reason_code(budget: BudgetDecisionV1, *, default: str) -> str:
    reason_code = budget.get("budget_reason_code")
    if isinstance(reason_code, str) and reason_code:
        return reason_code
    return default


def _domain_validation_reason_code(result: DomainValidationOutputV1, *, default: str) -> str:
    reason_codes = result.get("reason_codes") or []
    if reason_codes:
        first_reason_code = reason_codes[0]
        if isinstance(first_reason_code, str) and first_reason_code:
            return first_reason_code
    return default


def _preflight_result_code(result: JsonObject, *, default: str) -> str:
    result_code = result.get("result_code")
    if isinstance(result_code, str) and result_code:
        return result_code
    return default


def _preflight_safe_error_code(result: JsonObject) -> str | None:
    safe_error_code = result.get("safe_error_code")
    if isinstance(safe_error_code, str) and safe_error_code:
        return safe_error_code
    return None


def _partial_result_kind(state: MultiAgentGraphState, extra: JsonObject) -> str | None:
    for candidate in (extra.get("acquisition_result"), extra.get("context_result")):
        mapping = _mapping_or_none(candidate)
        if mapping is not None and mapping.get("status") == "PARTIAL":
            return "PARTIAL"
    acquisition = _mapping_or_none(state.get("acquisition_result"))
    if acquisition is not None and acquisition.get("status") == "PARTIAL":
        return "PARTIAL"
    context = _mapping_or_none(state.get("context_result"))
    if context is not None and context.get("status") == "PARTIAL":
        return "PARTIAL"
    return None


def _has_supported_evidence(current_update: Mapping[str, object]) -> bool:
    for key in ("context_result", "work_analysis_result"):
        result = _mapping_or_none(current_update.get(key))
        if result is None:
            continue
        evidence = result.get("evidence_drafts", result.get("evidence_refs"))
        if isinstance(evidence, list) and evidence:
            return True
    return False


def _mapping_or_none(value: object) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected mapping value")
    return cast(JsonObject, value)


def _require_mapping(value: object, name: str) -> JsonObject:
    mapping = _mapping_or_none(value)
    if mapping is None:
        raise ValueError(f"{name} is required")
    return mapping


def _claim_result_mapping(value: object, name: str) -> JsonObject:
    if isinstance(value, dict):
        return cast(JsonObject, value)
    if is_dataclass(value) and not isinstance(value, type):
        return cast(JsonObject, asdict(value))
    raise ValueError(f"{name} is required")


__all__ = [
    "RetrievalRouteResultV1",
    "SupervisorDecisionV1",
    "SupervisorTarget",
    "route_supervisor",
]
