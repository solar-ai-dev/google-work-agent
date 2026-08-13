"""Deterministic supervisor routing over frozen workflow contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import StrEnum
from typing import TypedDict, cast

from google_work_agent.application.workflows.api_acquisition import (
    build_source_planning_clarification_question,
)
from google_work_agent.application.workflows.context_retrieval import (
    build_context_clarification_question,
)
from google_work_agent.application.workflows.contracts import (
    BudgetDecision,
    BudgetDecisionV1,
    DomainValidationOutputV1,
    DomainValidationResult,
    FinalizeIntent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanningResult,
    RequestUnderstandingResult,
    ReviewResult,
    WorkflowPhase,
    approve_additional_acquisition,
    approve_planning_revision,
    approve_review_recheck,
    validate_finalize_intent_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ClarificationQuestionV1,
    ContextRetrievalResultV1,
    PlanReviewResultV1,
    RequestIntentV1,
    RequestUnderstandingOutputV1,
    SourcePlanningOutputV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.insufficient_data import (
    InsufficientDataContext,
    InsufficientDataDisposition,
    InsufficientDataIssue,
    ResolutionSource,
    decide_insufficient_data,
)
from google_work_agent.application.workflows.plan_review import (
    build_plan_review_clarification_question,
    resolve_review_target,
)
from google_work_agent.application.workflows.request_understanding import (
    build_user_interrupt_v1,
    validate_clarification_question_v1,
    validate_request_intent_v1,
)
from google_work_agent.application.workflows.solution_planning import (
    build_solution_planning_clarification_question,
)
from google_work_agent.application.workflows.work_analysis import (
    build_work_analysis_clarification_question,
)

JsonObject = dict[str, object]


class SupervisorTarget(StrEnum):
    """Deterministic routing targets selected by the Stage 10 supervisor."""

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


def route_supervisor(
    *,
    phase: WorkflowPhase | str,
    state: MultiAgentGraphState,
    result: object | None = None,
) -> SupervisorDecisionV1:
    current_phase = WorkflowPhase(phase)
    if current_phase is WorkflowPhase.REQUEST_ANALYSIS:
        return _route_request_understanding(
            state=state,
            output=cast(RequestUnderstandingOutputV1, _require_mapping(result, "result")),
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
        return _route_context(
            state=state,
            result=cast(ContextRetrievalResultV1, _require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.WORK_ANALYSIS:
        return _route_analysis(
            state=state,
            result=cast(WorkAnalysisResultV1, _require_mapping(result, "result")),
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
            result=cast(PlanReviewResultV1, _require_mapping(result, "result")),
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


def _route_request_understanding(
    *,
    state: MultiAgentGraphState,
    output: RequestUnderstandingOutputV1,
) -> SupervisorDecisionV1:
    result = RequestUnderstandingResult(output["result"])
    request_intent = output.get("request_intent")
    if result is RequestUnderstandingResult.COMPLETE:
        return _decision(
            target=SupervisorTarget.SOURCE_PLANNING,
            next_phase=WorkflowPhase.SOURCE_PLANNING,
            state_update=_base_state_update(
                WorkflowPhase.SOURCE_PLANNING,
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


def _route_context(
    *,
    state: MultiAgentGraphState,
    result: ContextRetrievalResultV1,
) -> SupervisorDecisionV1:
    status = str(result["status"])
    if status in {"SUFFICIENT", "PARTIAL"}:
        return _decision(
            target=SupervisorTarget.WORK_ANALYSIS,
            next_phase=WorkflowPhase.WORK_ANALYSIS,
            state_update=_base_state_update(
                WorkflowPhase.WORK_ANALYSIS,
                context_result=result,
            ),
            reason_code=status,
        )
    if status == "NEEDS_MORE_DATA":
        return _route_additional_acquisition(
            state=state,
            reason_code="CONTEXT_NEEDS_MORE_DATA",
            current_update={"context_result": result},
            request=result["additional_acquisition_request"],
        )
    if status == "NEEDS_CONFIRMATION":
        question = build_context_clarification_question(
            result=result,
            request_intent=_request_intent_from_state(state),
        )
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                context_result=result,
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code="CONTEXT_BLOCKED",
        context_result=result,
    )


def _route_analysis(
    *,
    state: MultiAgentGraphState,
    result: WorkAnalysisResultV1,
) -> SupervisorDecisionV1:
    status = str(result["status"])
    if status == "COMPLETE":
        return _decision(
            target=SupervisorTarget.SOLUTION_PLANNING,
            next_phase=WorkflowPhase.SOLUTION_PLANNING,
            state_update=_base_state_update(
                WorkflowPhase.SOLUTION_PLANNING,
                analysis_result=result,
            ),
            reason_code=status,
        )
    if status == "NEEDS_MORE_DATA":
        return _route_additional_acquisition(
            state=state,
            reason_code="WORK_ANALYSIS_NEEDS_MORE_DATA",
            current_update={"analysis_result": result},
            request=result["additional_acquisition_request"],
        )
    if status == "NEEDS_CONFIRMATION":
        question = build_work_analysis_clarification_question(
            result=result,
            request_intent=_request_intent_from_state(state),
        )
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                analysis_result=result,
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code="WORK_ANALYSIS_BLOCKED",
        analysis_result=result,
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
    result: PlanReviewResultV1,
) -> SupervisorDecisionV1:
    status = ReviewResult(str(result["status"]))
    review_update: GraphStateUpdateV1 = {"plan_review": result}
    if status is ReviewResult.PASS:
        target_kind, _draft = _review_target_from_state(state)
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
        budget = approve_planning_revision(state["retry_budget"])
        if budget["decision"] == BudgetDecision.DENY.value:
            return _finalize(
                state=state,
                intent=FinalizeIntent.BLOCKED.value,
                reason_code=_budget_reason_code(budget, default="PLANNING_REVISION_DENIED"),
                budget_decision=budget,
                current_update=review_update,
            )
        target_kind, _draft = _review_target_from_state(state)
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
        return _route_additional_acquisition(
            state=state,
            reason_code="PLAN_REVIEW_RETRIEVE_MORE",
            current_update=review_update,
            request=result["additional_acquisition_request"],
        )
    if status is ReviewResult.CONFIRM:
        question = build_plan_review_clarification_question(
            result=result,
            request_intent=_request_intent_from_state(state),
        )
        return _decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=_confirmation_state_update(
                question=question,
                **review_update,
            ),
            reason_code=question["reason_code"],
        )
    return _finalize(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code="PLAN_REVIEW_BLOCK",
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
        analysis_result=state.get("analysis_result"),
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


def _request_intent_from_state(state: MultiAgentGraphState) -> RequestIntentV1:
    return validate_request_intent_v1(
        _require_mapping(state.get("request_intent"), "request_intent")
    )


def _review_target_from_state(
    state: MultiAgentGraphState,
) -> tuple[str, AnswerDraftV1 | ActionPlanDraftV1]:
    return resolve_review_target(
        answer_draft=state["answer_draft"],
        plan_draft=state["plan_draft"],
    )


def _is_revision_follow_up(state: MultiAgentGraphState) -> bool:
    review = state["plan_review"]
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
    failure = _mapping_or_none(output.get("failure"))
    if (
        failure is not None
        and isinstance(failure.get("reason_code"), str)
        and failure["reason_code"]
    ):
        return cast(str, failure["reason_code"])
    request_intent = _mapping_or_none(output.get("request_intent"))
    unsupported = (
        None
        if request_intent is None
        else _mapping_or_none(request_intent.get("unsupported_scope"))
    )
    if (
        unsupported is not None
        and isinstance(unsupported.get("reason_code"), str)
        and unsupported["reason_code"]
    ):
        return cast(str, unsupported["reason_code"])
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
    for key in ("context_result", "analysis_result"):
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
    "SupervisorDecisionV1",
    "SupervisorTarget",
    "route_supervisor",
]
