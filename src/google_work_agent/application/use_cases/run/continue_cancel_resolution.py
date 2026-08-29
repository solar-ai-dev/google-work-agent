"""Coordinate durable child settlement for a Run already cancelling."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ContinueCancelResolutionCommandV1:
    schema_version: Literal[1]
    run_id: str


@dataclass(frozen=True, slots=True)
class ContinueCancelResolutionResultV1:
    schema_version: Literal[1]
    outcome: Literal["FINALIZED", "PROGRESSED", "WAITING_FOR_SETTLEMENT"]
    run_status: str
    progressed_action_id: str | None = None


class ContinueCancelResolutionHandler:
    """Select the next canonical child operation without duplicating its mutation."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        settle_pending_action: Callable[[str, int], bool],
        reconcile_inflight_action: Callable[[str], bool],
        verify_executed_action: Callable[[str], bool],
        resolve_unknown_action: Callable[[str], bool],
        finalize_cancel: Callable[[str, int], bool],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._settle_pending_action = settle_pending_action
        self._reconcile_inflight_action = reconcile_inflight_action
        self._verify_executed_action = verify_executed_action
        self._resolve_unknown_action = resolve_unknown_action
        self._finalize_cancel = finalize_cancel

    def __call__(
        self, command: ContinueCancelResolutionCommandV1
    ) -> ContinueCancelResolutionResultV1:
        if command.schema_version != 1:
            raise ValueError("unsupported cancel-resolution schema")
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            if run.status is not RunStatusV1.CANCEL_REQUESTED:
                raise ValueError("cancel resolution requires CANCEL_REQUESTED")
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: item.revision_no, default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            run_version = run.version

        for action in actions:
            status = ActionStatusV1(action.status)
            if status in {
                ActionStatusV1.PROPOSED,
                ActionStatusV1.MODIFIED,
                ActionStatusV1.APPROVED,
                ActionStatusV1.EXPIRED,
            }:
                progressed = self._settle_pending_action(action.id, action.version)
            elif status is ActionStatusV1.EXECUTING:
                progressed = self._reconcile_inflight_action(action.id)
            elif status is ActionStatusV1.UNKNOWN_RESULT:
                progressed = self._resolve_unknown_action(action.id)
            elif status is ActionStatusV1.EXECUTED:
                progressed = self._verify_executed_action(action.id)
            else:
                continue
            return ContinueCancelResolutionResultV1(
                1,
                "PROGRESSED" if progressed else "WAITING_FOR_SETTLEMENT",
                RunStatusV1.CANCEL_REQUESTED.value,
                action.id,
            )

        finalized = self._finalize_cancel(command.run_id, run_version)
        return ContinueCancelResolutionResultV1(
            1,
            "FINALIZED" if finalized else "WAITING_FOR_SETTLEMENT",
            RunStatusV1.CANCELLED.value if finalized else RunStatusV1.CANCEL_REQUESTED.value,
        )


__all__ = [
    "ContinueCancelResolutionCommandV1",
    "ContinueCancelResolutionHandler",
    "ContinueCancelResolutionResultV1",
]
