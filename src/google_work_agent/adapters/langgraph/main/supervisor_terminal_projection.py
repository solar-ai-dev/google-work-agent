"""Shared confirmation and terminal state projections for Supervisor rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import cast

from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    boundary_supervisor_state_update,
    make_supervisor_decision,
)
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationOutputV1,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import BudgetDecisionV1
from google_work_agent.application.use_cases.run.terminal_contract import (
    validate_finalize_intent_v1,
)

JsonObject = dict[str, object]


def confirmation_state_update(
    *,
    question: request_understanding_output.ClarificationQuestionV1,
    **extra: object,
) -> JsonObject:
    update: JsonObject = {
        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
        "user_interrupt": build_user_interrupt_v1(question),
        "finalize_intent": None,
    }
    update.update(extra)
    return update


def finalize_supervisor_result(
    *,
    state: GraphState,
    intent: str,
    reason_code: str,
    result_kind: str | None = None,
    budget_decision: BudgetDecisionV1 | None = None,
    current_update: Mapping[str, object] | None = None,
    **extra: object,
) -> SupervisorDecisionV1:
    state_update = boundary_supervisor_state_update(
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
    return make_supervisor_decision(
        target=SupervisorTarget.FINALIZE,
        next_phase=WorkflowPhase.FINALIZE,
        state_update=state_update,
        reason_code=reason_code,
        budget_decision=budget_decision,
    )


def request_intent_from_state(state: GraphState) -> RequestIntentV2:
    return cast(
        RequestIntentV2,
        require_mapping(state.get("request_intent"), "request_intent"),
    )


def review_target_from_state(state: GraphState) -> str:
    planning_result = cast(Mapping[str, object], state).get("planning_result")
    if isinstance(planning_result, Mapping):
        if isinstance(planning_result.get("answer"), str):
            return "ANSWER"
        if isinstance(planning_result.get("actions"), list):
            return "PLAN"
    raise ValueError("Review requires a Planning artifact")


def request_invalid_reason_code(
    output: request_understanding_output.RequestUnderstandingOutputV1,
) -> str:
    failure = mapping_or_none(output.get("failure"))
    if (
        failure is not None
        and isinstance(failure.get("reason_code"), str)
        and failure["reason_code"]
    ):
        return cast(str, failure["reason_code"])
    return "REQUEST_UNDERSTANDING_INVALID"


def budget_reason_code(budget: BudgetDecisionV1, *, default: str) -> str:
    reason_code = budget.get("budget_reason_code")
    return reason_code if isinstance(reason_code, str) and reason_code else default


def domain_validation_reason_code(
    result: DomainValidationOutputV1,
    *,
    default: str,
) -> str:
    reason_codes = result.get("reason_codes") or []
    if reason_codes and isinstance(reason_codes[0], str) and reason_codes[0]:
        return reason_codes[0]
    return default


def preflight_result_code(result: JsonObject, *, default: str) -> str:
    result_code = result.get("result_code")
    if isinstance(result_code, str) and result_code:
        return result_code
    control = mapping_or_none(result.get("__workflow_control__"))
    if control is not None:
        reason = control.get("reason", control.get("stage"))
        if isinstance(reason, str) and reason:
            return reason
    return default


def preflight_safe_error_code(result: JsonObject) -> str | None:
    safe_error_code = result.get("safe_error_code")
    if isinstance(safe_error_code, str) and safe_error_code:
        return safe_error_code
    control = mapping_or_none(result.get("__workflow_control__"))
    if control is not None:
        nested_code = control.get("safe_error_code")
        if isinstance(nested_code, str) and nested_code:
            return nested_code
    return None


def has_supported_evidence(current_update: Mapping[str, object]) -> bool:
    for key in ("retrieval_result", "work_analysis_result"):
        result = mapping_or_none(current_update.get(key))
        if result is not None:
            evidence = result.get("evidence_refs")
            if isinstance(evidence, list) and evidence:
                return True
    return False


def mapping_or_none(value: object) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected mapping value")
    return cast(JsonObject, value)


def require_mapping(value: object, name: str) -> JsonObject:
    mapping = mapping_or_none(value)
    if mapping is None:
        raise ValueError(f"{name} is required")
    return mapping


def claim_result_mapping(value: object, name: str) -> JsonObject:
    if isinstance(value, dict):
        return cast(JsonObject, value)
    if is_dataclass(value) and not isinstance(value, type):
        return cast(JsonObject, asdict(value))
    raise ValueError(f"{name} is required")


def _partial_result_kind(state: GraphState, extra: JsonObject) -> str | None:
    for candidate in (extra.get("acquisition_result"), extra.get("retrieval_result")):
        mapping = mapping_or_none(candidate)
        if mapping is not None and (
            mapping.get("status") == "PARTIAL" or mapping.get("coverage") == "PARTIAL"
        ):
            return "PARTIAL"
    acquisition = mapping_or_none(state.get("acquisition_result"))
    if acquisition is not None and acquisition.get("status") == "PARTIAL":
        return "PARTIAL"
    retrieval = mapping_or_none(state.get("retrieval_result"))
    if retrieval is not None and retrieval.get("coverage") == "PARTIAL":
        return "PARTIAL"
    return None


__all__ = [
    "JsonObject",
    "budget_reason_code",
    "claim_result_mapping",
    "confirmation_state_update",
    "domain_validation_reason_code",
    "finalize_supervisor_result",
    "has_supported_evidence",
    "mapping_or_none",
    "preflight_result_code",
    "preflight_safe_error_code",
    "request_intent_from_state",
    "request_invalid_reason_code",
    "require_mapping",
    "review_target_from_state",
]
