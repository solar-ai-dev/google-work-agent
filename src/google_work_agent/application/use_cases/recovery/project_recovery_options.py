"""Project the closed recovery reason × resolution matrix."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_OPTIONS = {
    "UNKNOWN_RESULT": ("RECHECK", "FAIL"),
    "VERIFICATION_MISMATCH": ("RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "FAIL"),
    "CHECKPOINT_MISMATCH": ("RECHECK", "CANCEL", "FAIL"),
    "CONTRACT_VIOLATION": ("CANCEL", "FAIL"),
}


@dataclass(frozen=True, slots=True)
class ProjectRecoveryOptionsQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ProjectRecoveryOptionsResultV1:
    reason_code: str
    target: str
    action_id: str | None
    allowed_resolution_kinds: tuple[str, ...]


class ProjectRecoveryOptionsHandler:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ProjectRecoveryOptionsQueryV1) -> ProjectRecoveryOptionsResultV1:
        with self._unit_of_work_factory() as unit_of_work:
            context = unit_of_work.recovery_contexts.load_current_context(query.run_id)
        if context is None:
            raise LookupError("durable RecoveryContextV1 is unavailable")
        reason = str(context["reason"])
        if reason not in _OPTIONS:
            raise ValueError("unsupported recovery reason")
        action_id = None if context.get("action_id") is None else str(context["action_id"])
        return ProjectRecoveryOptionsResultV1(
            reason,
            "ACTION" if action_id is not None else "RUN",
            action_id,
            _OPTIONS[reason],
        )


__all__ = [
    "ProjectRecoveryOptionsHandler",
    "ProjectRecoveryOptionsQueryV1",
    "ProjectRecoveryOptionsResultV1",
]
