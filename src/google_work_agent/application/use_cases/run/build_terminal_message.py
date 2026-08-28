"""Build deterministic terminal assistant-message input without I/O."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class BuildTerminalMessageQueryV1:
    run_id: str
    result_kind: Literal[
        "ANSWER",
        "READ_RESULT",
        "SUCCESS",
        "PARTIAL",
        "BLOCKED",
        "FAILED",
        "CANCELLED",
    ]
    content: str | None = None
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
        content = (
            _DEFAULT_TERMINAL_CONTENT[query.result_kind]
            if query.content is None
            else query.content.strip()
        )
        if not content:
            raise ValueError("terminal assistant content must not be blank")
        return TerminalAssistantMessageInputV1(
            1, query.run_id, "ASSISTANT", content, query.result_kind, query.safe_reason_code
        )


_DEFAULT_TERMINAL_CONTENT = {
    "ANSWER": "요청에 대한 답변을 완료했습니다.",
    "READ_RESULT": "요청한 조회를 완료했습니다.",
    "SUCCESS": "요청한 작업을 모두 완료했습니다.",
    "PARTIAL": "요청한 작업 중 일부만 완료했습니다.",
    "BLOCKED": "요청한 작업을 안전하게 진행할 수 없어 중단했습니다.",
    "FAILED": "요청한 작업을 완료하지 못했습니다.",
    "CANCELLED": "요청한 작업을 취소했습니다.",
}


__all__ = [
    "BuildTerminalMessageHandler",
    "BuildTerminalMessageQueryV1",
    "BuildTerminalMessageResult",
    "TerminalAssistantMessageInputV1",
]
