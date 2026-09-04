"""Canonical deterministic RESPONSE_SYNTHESIS control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
    TerminalActionOutcomeV1,
    TerminalActionStatusV1,
    TerminalAssistantMessageInputV1,
    TerminalEffectTypeV1,
    TerminalMessageSourceKindV1,
)

type TerminalCommitKindV1 = Literal[
    "COMPLETE_ANSWER_ONLY",
    "COMPLETE_READ_ONLY",
    "COMPLETE_WRITE",
    "BLOCK_RUN",
    "FINALIZE_CANCEL",
    "RECOVERY_ACCEPT_PARTIAL",
    "RECOVERY_CANCEL",
    "RECOVERY_FAIL",
]
type TerminalResultKindV1 = Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]


class TerminalCommitIntentV1(TypedDict):
    schema_version: Required[Literal[1]]
    kind: TerminalCommitKindV1
    expected_run_version: int
    terminal_message: TerminalAssistantMessageInputV1
    reason_codes: list[str]


_TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})
_TERMINAL_COMMIT_KINDS = frozenset(
    {
        "COMPLETE_ANSWER_ONLY",
        "COMPLETE_READ_ONLY",
        "COMPLETE_WRITE",
        "BLOCK_RUN",
        "FINALIZE_CANCEL",
        "RECOVERY_ACCEPT_PARTIAL",
        "RECOVERY_CANCEL",
        "RECOVERY_FAIL",
    }
)
_WRITE_FINAL_STATUSES = frozenset(
    {
        "VERIFIED",
        "REJECTED",
        "CANCELLED",
        "DEPENDENCY_BLOCKED",
        "BLOCKED",
    }
)
_READ_FINAL_STATUSES = frozenset({"VERIFIED", "FAILED"})


def response_synthesis_node(
    state: Mapping[str, object],
    *,
    read_terminal_facts: Callable[[str], Mapping[str, object]],
    build_terminal_message: BuildTerminalMessageHandler,
) -> dict[str, object]:
    """Build one terminal input/intent from already-decided durable facts."""

    run_id = _required_string(state.get("run_id"), "run_id")
    facts = read_terminal_facts(run_id)
    expected_version = _required_non_negative_int(facts.get("version"), "version")
    status = _required_string(facts.get("status"), "status")
    action_statuses = _string_tuple(facts.get("action_statuses"), "action_statuses")
    action_effect_types = _string_tuple(facts.get("action_effect_types"), "action_effect_types")
    finalize_intent = state.get("finalize_intent")

    kind, source_kind, result_kind, answer_text, reason_codes = _classify(
        state=state,
        status=status,
        terminal_result_kind=facts.get("terminal_result_kind"),
        action_statuses=action_statuses,
        action_effect_types=action_effect_types,
        finalize_intent=finalize_intent,
    )
    terminal_message = build_terminal_message(
        BuildTerminalMessageQueryV1(
            schema_version=1,
            run_id=run_id,
            expected_run_version=expected_version,
            source_kind=source_kind,
            result_kind=result_kind,
            answer_text=answer_text,
            reason_codes=reason_codes,
            request_text=_request_text(state),
            action_outcomes=_action_outcomes(facts.get("actions")),
        )
    )
    intent: TerminalCommitIntentV1 = {
        "schema_version": 1,
        "kind": kind,
        "expected_run_version": expected_version,
        "terminal_message": terminal_message,
        "reason_codes": reason_codes,
    }
    return {
        "__logical_target__": "terminal_commit",
        "__target__": "terminal_commit",
        "workflow_phase": "RESPONSE_SYNTHESIS",
        "terminal_commit_intent": intent,
    }


def validate_terminal_commit_intent(value: object) -> TerminalCommitIntentV1:
    if not isinstance(value, dict):
        raise ValueError("terminal_commit_intent must be an object")
    if set(value) != {
        "schema_version",
        "kind",
        "expected_run_version",
        "terminal_message",
        "reason_codes",
    }:
        raise ValueError("terminal_commit_intent fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("terminal_commit_intent schema_version must be 1")
    kind = value.get("kind")
    if kind not in _TERMINAL_COMMIT_KINDS:
        raise ValueError("terminal_commit_intent kind is invalid")
    _required_non_negative_int(value.get("expected_run_version"), "expected_run_version")
    if not isinstance(value.get("terminal_message"), TerminalAssistantMessageInputV1):
        raise ValueError("terminal_commit_intent terminal_message is invalid")
    reason_codes = value.get("reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("terminal_commit_intent reason_codes are invalid")
    return cast(TerminalCommitIntentV1, value)


def _classify(
    *,
    state: Mapping[str, object],
    status: str,
    terminal_result_kind: object,
    action_statuses: tuple[str, ...],
    action_effect_types: tuple[str, ...],
    finalize_intent: object,
) -> tuple[
    TerminalCommitKindV1,
    TerminalMessageSourceKindV1,
    TerminalResultKindV1,
    str | None,
    list[str],
]:
    answer_text = _answer_text(state.get("planning_result"))
    intent_name, intent_reason, intent_result = _finalize_fields(finalize_intent)
    durable_result = terminal_result_kind if isinstance(terminal_result_kind, str) else None

    if intent_name == "BLOCKED" or status == "BLOCKED":
        return "BLOCK_RUN", "POLICY_BLOCK", "BLOCKED", None, [intent_reason or "BLOCKED"]
    if status == "CANCELLED" or status == "CANCEL_REQUESTED":
        result: TerminalResultKindV1 = (
            cast(TerminalResultKindV1, durable_result)
            if durable_result in {"PARTIAL", "CANCELLED"}
            else "CANCELLED"
        )
        return "FINALIZE_CANCEL", "CANCEL_RESULT", result, None, ["CANCEL_REQUESTED"]
    if status == "FAILED":
        return (
            "RECOVERY_FAIL",
            "RECOVERY_RESULT",
            "FAILED",
            None,
            [intent_reason or "RECOVERY_FAIL"],
        )
    if intent_name == "FAILED" and status == "RECOVERY_REQUIRED":
        return (
            "RECOVERY_FAIL",
            "RECOVERY_RESULT",
            "FAILED",
            None,
            [intent_reason or "RECOVERY_FAIL"],
        )
    if answer_text is not None:
        result = cast(
            TerminalResultKindV1,
            "PARTIAL" if intent_result == "PARTIAL" or durable_result == "PARTIAL" else "SUCCESS",
        )
        return "COMPLETE_ANSWER_ONLY", "ANSWER_DRAFT", result, answer_text, []
    if action_effect_types and all(item == "READ" for item in action_effect_types):
        if not action_statuses or any(item not in _READ_FINAL_STATUSES for item in action_statuses):
            raise ValueError("READ terminal intent requires only VERIFIED/FAILED actions")
        result = cast(
            TerminalResultKindV1,
            "PARTIAL" if "FAILED" in action_statuses else "SUCCESS",
        )
        reasons = ["READ_ACTION_FAILED"] if result == "PARTIAL" else []
        return "COMPLETE_READ_ONLY", "READ_RESULT_SUMMARY", result, None, reasons
    if action_effect_types:
        if not action_statuses or any(
            item not in _WRITE_FINAL_STATUSES for item in action_statuses
        ):
            raise ValueError("WRITE terminal intent requires only closed action facts")
        result = cast(
            TerminalResultKindV1,
            "SUCCESS" if all(item == "VERIFIED" for item in action_statuses) else "PARTIAL",
        )
        reasons = ["WRITE_VERIFIED"] if result == "SUCCESS" else ["WRITE_CLOSED"]
        return "COMPLETE_WRITE", "WRITE_VERIFICATION_SUMMARY", result, None, reasons
    if status in _TERMINAL_STATUSES and durable_result in {"SUCCESS", "PARTIAL"}:
        raise ValueError("completed terminal facts do not identify a canonical handler")
    raise ValueError("current durable facts do not authorize terminal synthesis")


def _finalize_fields(value: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None, None
    intent = value.get("intent")
    reason = value.get("reason_code")
    result = value.get("result_kind")
    return (
        intent if isinstance(intent, str) else None,
        reason if isinstance(reason, str) else None,
        result if isinstance(result, str) else None,
    )


def _answer_text(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    is_current = value.get("schema_version") == 2 and isinstance(value.get("meta"), Mapping)
    if not is_current:
        return None
    answer = value.get("answer")
    return answer if isinstance(answer, str) and answer.strip() else None


def _request_text(state: Mapping[str, object]) -> str | None:
    run_input = state.get("run_input")
    if not isinstance(run_input, Mapping):
        return None
    user_request = run_input.get("user_request")
    return user_request if isinstance(user_request, str) and user_request.strip() else None


def _action_outcomes(value: object) -> tuple[TerminalActionOutcomeV1, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("actions must be a collection")
    result: list[TerminalActionOutcomeV1] = []
    closed_statuses = {
        "VERIFIED",
        "REJECTED",
        "FAILED",
        "MISMATCH",
        "BLOCKED",
        "DEPENDENCY_BLOCKED",
        "CANCELLED",
    }
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("actions must contain objects")
        status = item.get("status")
        if status not in closed_statuses:
            continue
        arguments = item.get("arguments")
        if not isinstance(arguments, Mapping):
            raise ValueError("action arguments must be an object")
        evidence_excerpts = item.get("evidence_excerpts", ())
        if not isinstance(evidence_excerpts, (list, tuple)) or any(
            not isinstance(excerpt, str) for excerpt in evidence_excerpts
        ):
            raise ValueError("action evidence_excerpts must be a string collection")
        result.append(
            TerminalActionOutcomeV1(
                tool_name=_required_string(item.get("tool_name"), "action.tool_name"),
                effect_type=cast(
                    TerminalEffectTypeV1,
                    _required_string(item.get("effect_type"), "action.effect_type"),
                ),
                status=cast(TerminalActionStatusV1, status),
                arguments=dict(arguments),
                evidence_excerpts=tuple(evidence_excerpts),
            )
        )
    return tuple(result)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a string collection")
    return tuple(value)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _required_non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


__all__ = [
    "TerminalCommitIntentV1",
    "TerminalCommitKindV1",
    "response_synthesis_node",
    "validate_terminal_commit_intent",
]
