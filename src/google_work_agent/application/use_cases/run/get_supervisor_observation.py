"""Read the minimal durable Run facts required by deterministic supervision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import next_allowed_run_commands
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class GetSupervisorObservationQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class SupervisorObservationV1:
    run_status: str
    next_allowed_commands: tuple[str, ...]
    action_statuses: tuple[str, ...]
    cancel_intent_active: bool


class GetSupervisorObservationHandler:
    """Project lifecycle facts without loading UI, recovery, or message details."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(
        self,
        query: GetSupervisorObservationQuery,
    ) -> SupervisorObservationV1 | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                return None
            plans = current_plan_tuple(unit_of_work.plans, query.run_id)
            action_statuses = tuple(
                action.status
                for plan in plans
                if plan.status is not PlanStatusV1.SUPERSEDED
                for action in unit_of_work.actions.list_for_plan(plan.id)
            )
            cancel_intent_active = has_durable_cancel_intent(
                unit_of_work.command_receipts,
                query.run_id,
            )
        return SupervisorObservationV1(
            run_status=run.status.value,
            next_allowed_commands=tuple(
                command.value for command in next_allowed_run_commands(run.status)
            ),
            action_statuses=action_statuses,
            cancel_intent_active=cancel_intent_active,
        )


__all__ = [
    "GetSupervisorObservationHandler",
    "GetSupervisorObservationQuery",
    "SupervisorObservationV1",
]
