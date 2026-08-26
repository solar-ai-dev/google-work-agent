"""Bounded startup/live reconciliation for durable workflow handoffs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class RedriveWorkflowHandoffsCommand:
    limit: int = 32


@dataclass(frozen=True, slots=True)
class RedriveWorkflowHandoffsResult:
    inspected: int
    accepted: int
    blocked_binding: int


class RedriveWorkflowHandoffsHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        schedule_run_execution: ScheduleRunExecutionHandler,
        reconcile_blocked_binding: Callable[[str], None] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._schedule_run_execution = schedule_run_execution
        self._reconcile_blocked_binding = reconcile_blocked_binding

    def __call__(
        self, command: RedriveWorkflowHandoffsCommand | None = None
    ) -> RedriveWorkflowHandoffsResult:
        command = command or RedriveWorkflowHandoffsCommand()
        if command.limit < 1:
            raise ValueError("redrive limit must be positive")
        with self._unit_of_work_factory() as unit_of_work:
            blocked = unit_of_work.workflow_handoffs.list_blocked_binding(command.limit)
            remaining = max(0, command.limit - len(blocked))
            redriveable = (
                unit_of_work.workflow_handoffs.list_redriveable(remaining) if remaining else []
            )

        for handoff in blocked:
            if self._reconcile_blocked_binding is not None:
                self._reconcile_blocked_binding(handoff.handoff_id)

        accepted = 0
        seen_runs: set[str] = set()
        for handoff in redriveable:
            if handoff.execution.run_id in seen_runs:
                continue
            seen_runs.add(handoff.execution.run_id)
            run_handoffs = [
                item
                for item in redriveable
                if item.execution.run_id == handoff.execution.run_id
            ]
            consumed = next(
                (
                    item
                    for item in run_handoffs
                    if item.status == "CONSUMED" and item.applied_checkpoint_id is not None
                ),
                None,
            )
            if consumed is not None:
                result = self._schedule_run_execution(
                    ScheduleRunExecutionCommand(
                        handoff_id=consumed.handoff_id,
                        submission_kind="CONSUMED_CONTINUATION_RECOVERY",
                    )
                )
                accepted += int(result.accepted)
                if result.accepted or result.reason_code == "ALREADY_RUNNING":
                    continue
            with self._unit_of_work_factory() as unit_of_work:
                head = unit_of_work.workflow_handoffs.get_dispatch_head(
                    handoff.execution.run_id
                )
            if head is None or head.status == "BLOCKED_BINDING":
                continue
            result = self._schedule_run_execution(
                ScheduleRunExecutionCommand(
                    handoff_id=head.handoff_id,
                    submission_kind="NORMAL_HANDOFF",
                )
            )
            accepted += int(result.accepted)
        return RedriveWorkflowHandoffsResult(
            inspected=len(blocked) + len(redriveable),
            accepted=accepted,
            blocked_binding=len(blocked),
        )
