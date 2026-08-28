"""Build deterministic terminal assistant-message input without I/O."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class BuildTerminalMessageQueryV1:
    run_id: str
    result_kind: Literal["ANSWER", "READ_RESULT", "PARTIAL", "BLOCKED", "FAILED"]
    content: str
    safe_reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class TerminalAssistantMessageInputV1:
    schema_version: int
    run_id: str
    role: Literal["ASSISTANT"]
    content: str
    result_kind: str
    safe_reason_code: str | None


BuildTerminalMessageResult = TerminalAssistantMessageInputV1


class BuildTerminalMessageHandler:
    def __call__(self, query: BuildTerminalMessageQueryV1) -> TerminalAssistantMessageInputV1:
        content = query.content.strip()
        if not content:
            raise ValueError("terminal assistant content must not be blank")
        return TerminalAssistantMessageInputV1(
            1, query.run_id, "ASSISTANT", content, query.result_kind, query.safe_reason_code
        )


__all__ = [
    "BuildTerminalMessageHandler",
    "BuildTerminalMessageQueryV1",
    "BuildTerminalMessageResult",
    "TerminalAssistantMessageInputV1",
]
