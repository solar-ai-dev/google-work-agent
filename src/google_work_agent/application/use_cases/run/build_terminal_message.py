"""Build the canonical deterministic terminal assistant-message input."""

from dataclasses import dataclass
from typing import Literal

type TerminalMessageSourceKindV1 = Literal[
    "ANSWER_DRAFT",
    "WRITE_VERIFICATION_SUMMARY",
    "POLICY_BLOCK",
    "CANCEL_RESULT",
    "RECOVERY_RESULT",
    "INVALID_REQUEST",
]
type _TerminalResultKindLiteralV1 = Literal[
    "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"
]


@dataclass(frozen=True, slots=True)
class BuildTerminalMessageQueryV1:
    schema_version: Literal[1]
    run_id: str
    expected_run_version: int
    source_kind: TerminalMessageSourceKindV1
    result_kind: _TerminalResultKindLiteralV1
    answer_text: str | None
    reason_codes: list[str]


@dataclass(frozen=True, slots=True)
class TerminalAssistantMessageInputV1:
    schema_version: Literal[1]
    result_kind: _TerminalResultKindLiteralV1
    content: str
    reason_codes: list[str]


BuildTerminalMessageResult = TerminalAssistantMessageInputV1


class BuildTerminalMessageHandler:
    """Format a bounded terminal projection without I/O or lifecycle decisions."""

    def __call__(self, query: BuildTerminalMessageQueryV1) -> TerminalAssistantMessageInputV1:
        _validate_query(query)
        if query.source_kind == "ANSWER_DRAFT":
            assert query.answer_text is not None
            content = query.answer_text
        else:
            content = _DEFAULT_TERMINAL_CONTENT[query.result_kind]
            if query.reason_codes:
                content = f"{content} Reason codes: {', '.join(query.reason_codes)}."
        if not 1 <= len(content.encode("utf-8")) <= 65_536:
            raise ValueError("terminal assistant content must be 1..65536 UTF-8 bytes")
        return TerminalAssistantMessageInputV1(
            schema_version=1,
            result_kind=query.result_kind,
            content=content,
            reason_codes=list(query.reason_codes),
        )


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


_DEFAULT_TERMINAL_CONTENT: dict[_TerminalResultKindLiteralV1, str] = {
    "SUCCESS": "The requested work completed successfully.",
    "PARTIAL": "The requested work completed partially.",
    "BLOCKED": "The requested work was blocked safely.",
    "FAILED": "The requested work could not be completed.",
    "CANCELLED": "The requested work was cancelled.",
}


__all__ = [
    "BuildTerminalMessageHandler",
    "BuildTerminalMessageQueryV1",
    "BuildTerminalMessageResult",
    "TerminalAssistantMessageInputV1",
    "TerminalMessageSourceKindV1",
]
