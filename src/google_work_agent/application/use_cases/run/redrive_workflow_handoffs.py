"""Bounded startup/live reconciliation for durable workflow handoffs.

Owns both ordinary redrive dispatch and BLOCKED_BINDING reconciliation
(08-sequence-design.md: BLOCKED_BINDING dispatch head -> deterministic
RequireRecovery(CHECKPOINT_MISMATCH) -> matching RecoveryContext confirmed ->
handoff SUPERSEDED) as one Application capability -- there is exactly one
production handoff-reconciliation authority. The Run transition + durable
RecoveryContextV1 write remain owned exclusively by ``RequireRecoveryHandler``;
resume-target/binding legality remains owned exclusively by
``ResumeTargetRegistry`` (consumed indirectly via ``ScheduleRunExecutionHandler``,
never duplicated here).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import TERMINAL_RUN_STATUSES
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import WorkflowHandoffV1

_RUN_NOT_EXECUTABLE = "RUN_NOT_EXECUTABLE"
_CHECKPOINT_MISMATCH_RECOVERED = "CHECKPOINT_MISMATCH_RECOVERED"


@dataclass(frozen=True, slots=True)
class RedriveWorkflowHandoffsCommand:
    limit: int = 32


@dataclass(frozen=True, slots=True)
class RedriveWorkflowHandoffsResult:
    inspected: int
    accepted: int
    blocked_binding: int


class RedriveWorkflowHandoffsHandler:
    """Sole production owner of workflow-handoff reconciliation (startup + live)."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        schedule_run_execution: ScheduleRunExecutionHandler,
        require_recovery: RequireRecoveryHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._schedule_run_execution = schedule_run_execution
        self._require_recovery = require_recovery

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
            if not self._may_dispatch(head):
                continue
            assert head is not None
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

    def _may_dispatch(self, head: WorkflowHandoffV1 | None) -> bool:
        """Domain-progress pre-admission fence: never submit a NORMAL handoff head
        while a competing Domain authority (BLOCKED_BINDING settlement in flight, or
        the owning Run has already moved into a Recovery/Reauth/cancel/terminal
        state) governs the run. ``ScheduleRunExecutionHandler`` itself has no such
        gate for NORMAL_HANDOFF submissions, so this check is the sole fence.
        """
        if head is None or head.status == "BLOCKED_BINDING":
            return False
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(head.execution.run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return False
        return run.status not in {
            RunStatus.REAUTH_REQUIRED,
            RunStatus.RECOVERY_REQUIRED,
            RunStatus.CANCEL_REQUESTED,
        }

    def _reconcile_blocked_binding(self, handoff_id: str) -> None:
        """Canonical 7-step BLOCKED_BINDING reconciliation sequence: reload ->
        Domain-authority preemption check -> deterministic
        RequireRecovery(CHECKPOINT_MISMATCH) -> reload -> supersede only on a
        matching durable RecoveryContext, else fail closed.
        """
        if self._require_recovery is None:
            return
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return
            run = unit_of_work.runs.get_by_id(handoff.execution.run_id)

        if run is None:
            return

        if run.status in TERMINAL_RUN_STATUSES:
            self._supersede_if_still_blocked(handoff_id, _RUN_NOT_EXECUTABLE)
            return

        if run.status in {RunStatus.REAUTH_REQUIRED, RunStatus.CANCEL_REQUESTED}:
            # A different Domain authority already governs this run -- never create a
            # competing CHECKPOINT_MISMATCH recovery merely to retire the handoff.
            return

        fingerprint = _reconciliation_fingerprint(handoff)

        if run.status is not RunStatus.RECOVERY_REQUIRED:
            require_recovery_command = RequireRecoveryCommand(
                run_id=run.id,
                expected_version=run.version,
                command_id=f"system:handoff-binding-recovery:{handoff_id}",
                request_hash=fingerprint,
                reason="CHECKPOINT_MISMATCH",
                scope="RUN",
                recovery_fingerprint=fingerprint,
                registered_resume_target=handoff.execution.resume_target,
                contract_or_checkpoint_fingerprint=fingerprint,
            )
            require_recovery_result = self._require_recovery(require_recovery_command)
            if not require_recovery_result.applied:
                return

        self._supersede_if_matching(handoff_id, fingerprint)

    def _supersede_if_still_blocked(self, handoff_id: str, reason_code: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, reason_code
            )
            unit_of_work.commit()

    def _supersede_if_matching(self, handoff_id: str, fingerprint: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return
            run = unit_of_work.runs.get_by_id(handoff.execution.run_id)
            if run is None or run.status is not RunStatus.RECOVERY_REQUIRED:
                return
            context = unit_of_work.recovery_contexts.load_current_context(
                handoff.execution.run_id
            )
            if (
                context is None
                or context["reason"] != "CHECKPOINT_MISMATCH"
                or context.get("recovery_fingerprint") != fingerprint
            ):
                # Fail closed: a different (or non-matching) current Recovery authority
                # governs this run -- never overwrite it merely to retire the handoff.
                return
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, _CHECKPOINT_MISMATCH_RECOVERED
            )
            unit_of_work.commit()


def _reconciliation_fingerprint(handoff: WorkflowHandoffV1) -> str:
    resume_target = handoff.execution.resume_target
    return calculate_canonical_json_hash(
        {
            "handoff_id": handoff.handoff_id,
            "run_id": handoff.execution.run_id,
            "langgraph_thread_id": handoff.execution.langgraph_thread_id,
            "graph_profile": handoff.execution.graph_profile,
            "graph_version": handoff.execution.graph_version,
            "checkpoint_id": handoff.checkpoint_id,
            "checkpoint_generation": handoff.checkpoint_generation,
            "resume_target": None if resume_target is None else asdict(resume_target),
        }
    )
