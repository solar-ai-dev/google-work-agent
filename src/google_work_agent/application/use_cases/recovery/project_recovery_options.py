"""Project the closed recovery reason × resolution matrix."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    project_allowed_recovery_resolutions,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ProjectRecoveryOptionsQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ProjectRecoveryOptionsResultV1:
    reason_code: str
    message: str
    target: dict[str, str]
    allowed_resolution_kinds: tuple[str, ...]


class ProjectRecoveryOptionsHandler:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ProjectRecoveryOptionsQueryV1) -> ProjectRecoveryOptionsResultV1:
        with self._unit_of_work_factory() as unit_of_work:
            context = unit_of_work.recovery_contexts.load_current_context(query.run_id)
            if context is None:
                raise LookupError("durable RecoveryContextV1 is unavailable")
            options = tuple(
                resolution.value
                for resolution in project_allowed_recovery_resolutions(unit_of_work, context)
            )
            reason = context["reason"]
            request_text = _request_text(unit_of_work, query.run_id)
            action_id = None if context.get("action_id") is None else str(context["action_id"])
        return ProjectRecoveryOptionsResultV1(
            reason,
            _recovery_message(reason, korean=_uses_korean(request_text)),
            (
                {"target_kind": "RUN"}
                if action_id is None
                else {"target_kind": "ACTION", "action_id": action_id}
            ),
            options,
        )


def _request_text(unit_of_work: UnitOfWork, run_id: str) -> str | None:
    run = unit_of_work.runs.get(run_id)
    if run is None:
        return None
    messages, _ = unit_of_work.messages.list_by_conversation_keyset(
        conversation_id=run.conversation_id,
        cursor=None,
        page_size=200,
    )
    message = next(
        (item for item in messages if item.run_id == run_id and item.role == "USER"),
        None,
    )
    return None if message is None else message.content


def _uses_korean(value: str | None) -> bool:
    return value is None or any("\uac00" <= character <= "\ud7a3" for character in value)


def _recovery_message(reason: str, *, korean: bool) -> str:
    if korean:
        return {
            "UNKNOWN_RESULT": (
                "Google에 요청이 전달됐을 수 있어 실제 결과를 먼저 확인해야 합니다. "
                "같은 작업을 다시 보내지 않고 안전하게 확인하겠습니다."
            ),
            "VERIFICATION_MISMATCH": (
                "Google에서 다시 확인한 결과가 요청한 내용과 일치하지 않습니다. "
                "현재 결과를 확인하고 다음 처리 방법을 선택해 주세요."
            ),
            "CHECKPOINT_MISMATCH": (
                "저장된 진행 위치와 현재 실행 상태가 일치하지 않아 자동으로 계속할 수 없습니다. "
                "안전한 지점부터 다시 확인할 수 있습니다."
            ),
            "CONTRACT_VIOLATION": (
                "안전한 실행 조건을 확인하지 못해 작업을 중단했습니다. "
                "현재 상태를 다시 확인한 뒤 계속할 수 있습니다."
            ),
        }[reason]
    return {
        "UNKNOWN_RESULT": (
            "The request may have reached Google, so I need to verify the actual result first. "
            "I will not resend the same action blindly."
        ),
        "VERIFICATION_MISMATCH": (
            "The result verified in Google does not match your request. "
            "Please review the current result and choose how to continue."
        ),
        "CHECKPOINT_MISMATCH": (
            "The saved progress point does not match the current run state, so I cannot continue "
            "automatically. You can recheck from a safe point."
        ),
        "CONTRACT_VIOLATION": (
            "I stopped because the required safety contract could not be confirmed. "
            "You can recheck the current state before continuing."
        ),
    }[reason]


__all__ = [
    "ProjectRecoveryOptionsHandler",
    "ProjectRecoveryOptionsQueryV1",
    "ProjectRecoveryOptionsResultV1",
]
