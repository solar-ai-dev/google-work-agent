"""Build the canonical deterministic terminal assistant-message input."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.run.format_blocked_terminal_message import (
    format_blocked_terminal_message,
)

type TerminalMessageSourceKindV1 = Literal[
    "ANSWER_DRAFT",
    "READ_RESULT_SUMMARY",
    "WRITE_VERIFICATION_SUMMARY",
    "POLICY_BLOCK",
    "CANCEL_RESULT",
    "RECOVERY_RESULT",
    "INVALID_REQUEST",
]
type TerminalResultKindV1 = Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]
type TerminalEffectTypeV1 = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
type TerminalActionStatusV1 = Literal[
    "VERIFIED",
    "REJECTED",
    "FAILED",
    "MISMATCH",
    "BLOCKED",
    "DEPENDENCY_BLOCKED",
    "CANCELLED",
]


@dataclass(frozen=True, slots=True)
class TerminalActionOutcomeV1:
    tool_name: str
    effect_type: TerminalEffectTypeV1
    status: TerminalActionStatusV1
    arguments: Mapping[str, object]
    evidence_excerpts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildTerminalMessageQueryV1:
    schema_version: Literal[1]
    run_id: str
    expected_run_version: int
    source_kind: TerminalMessageSourceKindV1
    result_kind: TerminalResultKindV1
    answer_text: str | None
    reason_codes: list[str]
    request_text: str | None = None
    action_outcomes: tuple[TerminalActionOutcomeV1, ...] = ()


@dataclass(frozen=True, slots=True)
class TerminalAssistantMessageInputV1:
    schema_version: Literal[1]
    result_kind: TerminalResultKindV1
    content: str
    reason_codes: list[str]


class BuildTerminalMessageHandler:
    """Format a bounded terminal projection without I/O or lifecycle decisions."""

    def __call__(self, query: BuildTerminalMessageQueryV1) -> TerminalAssistantMessageInputV1:
        _validate_query(query)
        if query.source_kind == "ANSWER_DRAFT":
            assert query.answer_text is not None
            content = query.answer_text
        else:
            content = _format_terminal_content(query)
        return validate_terminal_assistant_message_input(
            TerminalAssistantMessageInputV1(
                schema_version=1,
                result_kind=query.result_kind,
                content=content,
                reason_codes=list(query.reason_codes),
            )
        )


def validate_terminal_assistant_message_input(
    value: TerminalAssistantMessageInputV1,
) -> TerminalAssistantMessageInputV1:
    if value.schema_version != 1:
        raise ValueError("terminal assistant message schema_version must be 1")
    if value.result_kind not in {"SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"}:
        raise ValueError("terminal assistant message result_kind is invalid")
    if not 1 <= len(value.content.encode("utf-8")) <= 65_536:
        raise ValueError("terminal assistant content must be 1..65536 UTF-8 bytes")
    if len(value.reason_codes) > 16 or any(
        not code.strip() or len(code) > 64 for code in value.reason_codes
    ):
        raise ValueError("terminal assistant reason codes are invalid")
    return value


def _validate_query(query: BuildTerminalMessageQueryV1) -> None:
    if query.schema_version != 1:
        raise ValueError("terminal message schema_version must be 1")
    if not query.run_id.strip():
        raise ValueError("terminal message run_id must not be blank")
    if query.expected_run_version < 0:
        raise ValueError("expected_run_version must not be negative")
    if len(query.reason_codes) > 16:
        raise ValueError("terminal message reason_codes must contain at most 16 items")
    if any(not code.strip() or len(code) > 64 for code in query.reason_codes):
        raise ValueError("terminal message reason codes must be 1..64 characters")
    if query.source_kind == "ANSWER_DRAFT":
        if query.answer_text is None or not query.answer_text.strip():
            raise ValueError("ANSWER_DRAFT requires non-blank answer_text")
    elif query.answer_text is not None:
        raise ValueError("answer_text is only allowed for ANSWER_DRAFT")
    if query.request_text is not None and len(query.request_text.encode("utf-8")) > 16_384:
        raise ValueError("terminal message request_text exceeds 16384 UTF-8 bytes")
    if len(query.action_outcomes) > 50:
        raise ValueError("terminal message action_outcomes must contain at most 50 items")
    for outcome in query.action_outcomes:
        if not outcome.tool_name.strip() or len(outcome.tool_name) > 128:
            raise ValueError("terminal action tool_name must be 1..128 characters")
        if outcome.effect_type not in {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}:
            raise ValueError("terminal action effect_type is invalid")
        if outcome.status not in {
            "VERIFIED",
            "REJECTED",
            "FAILED",
            "MISMATCH",
            "BLOCKED",
            "DEPENDENCY_BLOCKED",
            "CANCELLED",
        }:
            raise ValueError("terminal action status is invalid")
        if not isinstance(outcome.arguments, Mapping):
            raise ValueError("terminal action arguments must be an object")
        if len(outcome.evidence_excerpts) > 20 or any(
            not excerpt.strip() or len(excerpt.encode("utf-8")) > 2_048
            for excerpt in outcome.evidence_excerpts
        ):
            raise ValueError("terminal action evidence excerpts are invalid")


def _format_terminal_content(query: BuildTerminalMessageQueryV1) -> str:
    has_verified_action = any(outcome.status == "VERIFIED" for outcome in query.action_outcomes)
    action_lines = tuple(
        _format_action_outcome(outcome) for outcome in query.action_outcomes[:8]
    )
    if len(query.action_outcomes) > 8:
        remaining = len(query.action_outcomes) - 8
        action_lines += (
            f"- 그 밖의 {remaining}개 작업도 같은 실행 결과에 포함됩니다.",
        )

    heading = {
        "SUCCESS": "요청하신 작업을 완료했습니다.",
        "PARTIAL": (
            "요청하신 작업 중 일부만 완료했습니다."
            if has_verified_action
            else "요청하신 작업을 완료하지 않았습니다."
        ),
        "BLOCKED": (
            "요청을 처리하는 데 필요한 조건을 충족하지 못해 안전하게 중단했습니다."
            if query.source_kind == "INVALID_REQUEST"
            else "안전 정책 또는 필수 조건 때문에 요청하신 작업을 실행하지 않았습니다."
        ),
        "FAILED": "요청하신 작업을 완료하지 못했습니다.",
        "CANCELLED": "요청하신 작업을 취소했습니다.",
    }[query.result_kind]
    if action_lines:
        return f"{heading}\n\n" + "\n".join(action_lines)
    if query.result_kind == "BLOCKED":
        return format_blocked_terminal_message(
            korean=True,
            source_kind=query.source_kind,
            reason_codes=query.reason_codes,
        )
    ending = {
        "SUCCESS": "확인 가능한 결과를 반영했습니다.",
        "PARTIAL": "완료된 변경과 완료되지 않은 항목을 구분해 반영했습니다.",
        "BLOCKED": "Google 변경은 실행하지 않았습니다.",
        "FAILED": "완료되지 않은 상태이며 성공으로 처리하지 않았습니다.",
        "CANCELLED": "확인된 Google 변경 없이 종료했습니다.",
    }[query.result_kind]
    return f"{heading} {ending}"


def _format_action_outcome(outcome: TerminalActionOutcomeV1) -> str:
    label = _action_label(outcome)
    read_evidence = _read_evidence_summary(outcome.evidence_excerpts)
    detail = {
        "VERIFIED": {
            "READ": (
                f"자료에서 확인한 내용은 {read_evidence}입니다."
                if read_evidence is not None
                else "자료를 읽었지만 표시할 수 있는 내용은 확인되지 않았습니다."
            ),
            "CREATE": "생성했고 Google에서 결과를 다시 확인했습니다.",
            "UPDATE": "변경했고 Google에서 결과를 다시 확인했습니다.",
            "SEND": "전송했고 Google에서 결과를 다시 확인했습니다.",
            "DELETE": "삭제했고 Google에서 결과를 다시 확인했습니다.",
        }[outcome.effect_type],
        "REJECTED": "사용자 선택에 따라 실행하지 않았습니다.",
        "FAILED": "완료하지 못했습니다.",
        "MISMATCH": "실행 결과가 요청한 내용과 일치하지 않아 완료로 처리하지 않았습니다.",
        "BLOCKED": "안전 조건을 충족하지 못해 실행하지 않았습니다.",
        "DEPENDENCY_BLOCKED": "필요한 선행 작업이 완료되지 않아 실행하지 않았습니다.",
        "CANCELLED": "완료 전에 취소했습니다.",
    }[outcome.status]
    return f"- {label}: {detail}"


def _action_label(outcome: TerminalActionOutcomeV1) -> str:
    tool_name = outcome.tool_name
    if tool_name.startswith("tasks_"):
        noun = "태스크"
    elif tool_name.startswith("calendar_"):
        noun = "일정"
    elif tool_name == "gmail_create_draft" or "draft" in tool_name:
        noun = "메일 초안"
    elif tool_name.startswith("gmail_"):
        noun = "메일"
    else:
        noun = "Google 작업"
    title = _display_value(_argument_value(outcome.arguments, "title", "subject"))
    return noun if title is None else f"{noun} ‘{title}’"


def _argument_value(arguments: Mapping[str, object], *fields: str) -> object | None:
    payload = arguments.get("payload")
    nested: Mapping[str, object] = payload if isinstance(payload, Mapping) else {}
    for field in fields:
        value = nested.get(field, arguments.get(field))
        if value is not None and value != "":
            return value
    return None


def _display_value(value: object | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text if len(text) <= 80 else f"{text[:77]}..."


def _read_evidence_summary(excerpts: tuple[str, ...]) -> str | None:
    values = tuple(text for text in (" ".join(excerpt.split()) for excerpt in excerpts[:5]) if text)
    if not values:
        return None
    summary = "; ".join(values)
    return summary if len(summary) <= 1_000 else f"{summary[:997]}..."



__all__ = [
    "BuildTerminalMessageHandler",
    "BuildTerminalMessageQueryV1",
    "TerminalActionOutcomeV1",
    "TerminalActionStatusV1",
    "TerminalAssistantMessageInputV1",
    "TerminalEffectTypeV1",
    "TerminalMessageSourceKindV1",
    "validate_terminal_assistant_message_input",
]
