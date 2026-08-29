"""Project the closed recovery reason × resolution matrix."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.recovery.model import RECOVERY_RESOLUTION_MATRIX
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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
            cancel_intent_active = has_durable_cancel_intent(
                unit_of_work.cancel_intents, query.run_id
            )
            actions = tuple(
                action
                for plan in current_plan_tuple(unit_of_work.plans, query.run_id)
                for action in unit_of_work.actions.list_for_plan(plan.id)
            )
        if context is None:
            raise LookupError("durable RecoveryContextV1 is unavailable")
        reason = context["reason"]
        if reason not in RECOVERY_RESOLUTION_MATRIX:
            raise ValueError("unsupported recovery reason")
        action_id = None if context.get("action_id") is None else str(context["action_id"])
        unresolved = any(
            action.status
            in {
                ActionStatusV1.EXECUTING.value,
                ActionStatusV1.UNKNOWN_RESULT.value,
                ActionStatusV1.EXECUTED.value,
            }
            for action in actions
        )
        options = tuple(
            resolution.value
            for resolution in RECOVERY_RESOLUTION_MATRIX[reason]
            if not (
                cancel_intent_active
                and resolution.value in {"ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "FAIL"}
            )
            if not (
                resolution.value == "CANCEL"
                and (
                    not cancel_intent_active
                    or unresolved
                    or (
                        reason == "UNKNOWN_RESULT"
                        and not any(
                            action.id == action_id
                            and action.status
                            in {ActionStatusV1.EXECUTED.value, ActionStatusV1.FAILED.value}
                            for action in actions
                        )
                    )
                )
            )
            if not (resolution.value == "FAIL" and unresolved)
        )
        return ProjectRecoveryOptionsResultV1(
            reason,
            "ACTION" if action_id is not None else "RUN",
            action_id,
            options,
        )


__all__ = [
    "ProjectRecoveryOptionsHandler",
    "ProjectRecoveryOptionsQueryV1",
    "ProjectRecoveryOptionsResultV1",
]
