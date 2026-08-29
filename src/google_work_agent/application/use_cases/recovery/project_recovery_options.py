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
            action_id = None if context.get("action_id") is None else str(context["action_id"])
        return ProjectRecoveryOptionsResultV1(
            reason,
            (
                {"target_kind": "RUN"}
                if action_id is None
                else {"target_kind": "ACTION", "action_id": action_id}
            ),
            options,
        )


__all__ = [
    "ProjectRecoveryOptionsHandler",
    "ProjectRecoveryOptionsQueryV1",
    "ProjectRecoveryOptionsResultV1",
]
