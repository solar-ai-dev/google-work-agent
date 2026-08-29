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
from google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart import (
    ReconcileRetrievalCacheRestartCommandV1,
    ReconcileRetrievalCacheRestartHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
    handoff_matches_preempting_run_authority,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.recovery.model import RecoveryReasonV1
from google_work_agent.domain.run.model import (
    RunStatusV1,
    is_preempting_run_status,
    is_terminal_run_status,
)
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
    progressed_count: int
    actionable_count: int
    has_more: bool


class RedriveWorkflowHandoffsHandler:
    """Sole production owner of workflow-handoff reconciliation (startup + live)."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        schedule_run_execution: ScheduleRunExecutionHandler,
        require_recovery: RequireRecoveryHandler,
        reconcile_retrieval_cache_restart: ReconcileRetrievalCacheRestartHandler | None = None,
        is_run_execution_active: Callable[[str], bool] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._schedule_run_execution = schedule_run_execution
        self._require_recovery = require_recovery
        self._reconcile_retrieval_cache_restart = reconcile_retrieval_cache_restart
        self._is_run_execution_active = is_run_execution_active or (lambda _run_id: False)

    def __call__(
        self, command: RedriveWorkflowHandoffsCommand | None = None
    ) -> RedriveWorkflowHandoffsResult:
        command = command or RedriveWorkflowHandoffsCommand()
        if command.limit < 1:
            raise ValueError("redrive limit must be positive")
        with self._unit_of_work_factory() as unit_of_work:
            actionable_count = unit_of_work.workflow_handoffs.count_redriveable()
            candidates = unit_of_work.workflow_handoffs.list_redriveable(command.limit)
        has_more = actionable_count > len(candidates)

        accepted = 0
        blocked_binding = 0
        progressed_count = 0
        for handoff in candidates:
            run_id = handoff.execution.run_id
            if self._is_run_execution_active(run_id):
                continue
            with self._unit_of_work_factory() as unit_of_work:
                current_run = unit_of_work.runs.get(run_id)
            if current_run is None or (
                is_preempting_run_status(current_run.status)
                and handoff.status != "BLOCKED_BINDING"
                and not handoff_matches_preempting_run_authority(
                    current_run.status, handoff
                )
            ):
                continue
            if (
                handoff.execution.execution_kind == "RESUME"
                and self._reconcile_retrieval_cache_restart is not None
            ):
                cache_result = self._reconcile_retrieval_cache_restart(
                    ReconcileRetrievalCacheRestartCommandV1(1, run_id)
                )
                if (
                    cache_result.outcome != "NO_RESTART_REQUIRED"
                    and cache_result.handoff_id != handoff.handoff_id
                ):
                    progressed_count += int(cache_result.outcome == "RESTART_STAGED")
                    continue
            if handoff.status == "CONSUMED" and handoff.applied_checkpoint_id is not None:
                result = self._schedule_run_execution(
                    ScheduleRunExecutionCommand(
                        handoff_id=handoff.handoff_id,
                        submission_kind="CONSUMED_CONTINUATION_RECOVERY",
                    )
                )
                accepted += int(result.accepted)
                progressed_count += int(result.accepted)
                continue
            if handoff.status == "BLOCKED_BINDING":
                blocked_binding += 1
                if self._reconcile_blocked_binding(handoff.handoff_id, handoff.version):
                    progressed_count += 1
                continue
            with self._unit_of_work_factory() as unit_of_work:
                head = unit_of_work.workflow_handoffs.get_dispatch_head(handoff.execution.run_id)
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
            progressed_count += int(result.accepted)
        return RedriveWorkflowHandoffsResult(
            inspected=len(candidates),
            accepted=accepted,
            blocked_binding=blocked_binding,
            progressed_count=progressed_count,
            actionable_count=actionable_count,
            has_more=has_more,
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
            run = unit_of_work.runs.get(head.execution.run_id)
        return run is not None and (
            not is_preempting_run_status(run.status)
            or handoff_matches_preempting_run_authority(run.status, head)
        )

    def _reconcile_blocked_binding(self, handoff_id: str, expected_version: int) -> bool:
        """Canonical 7-step BLOCKED_BINDING reconciliation sequence: reload ->
        Domain-authority preemption check -> deterministic
        RequireRecovery(CHECKPOINT_MISMATCH) -> reload -> supersede only on a
        matching durable RecoveryContext, else fail closed.
        """
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return False
            run = unit_of_work.runs.get(handoff.execution.run_id)

        if run is None:
            return False

        if is_terminal_run_status(run.status):
            return self._supersede_if_still_blocked(
                handoff_id, expected_version, _RUN_NOT_EXECUTABLE
            )

        if run.status in {RunStatusV1.REAUTH_REQUIRED, RunStatusV1.CANCEL_REQUESTED}:
            # A different Domain authority already governs this run -- never create a
            # competing CHECKPOINT_MISMATCH recovery merely to retire the handoff.
            return False

        fingerprint = _reconciliation_fingerprint(handoff)
        recovery_reason: RecoveryReasonV1 = (
            "CHECKPOINT_MISMATCH"
            if handoff.execution.resume_target is not None
            else "CONTRACT_VIOLATION"
        )

        if run.status is not RunStatusV1.RECOVERY_REQUIRED:
            require_recovery_command = RequireRecoveryCommand(
                run_id=run.id,
                expected_version=run.version,
                command_id=f"system:handoff-binding-recovery:{handoff_id}",
                request_hash=fingerprint,
                reason=recovery_reason,
                scope="RUN",
                recovery_fingerprint=fingerprint,
                registered_resume_target=handoff.execution.resume_target,
                contract_or_checkpoint_fingerprint=fingerprint,
            )
            require_recovery_result = self._require_recovery(require_recovery_command)
            if not require_recovery_result.applied:
                return False

        return self._supersede_if_matching(
            handoff_id, expected_version, fingerprint, recovery_reason
        )

    def _supersede_if_still_blocked(
        self, handoff_id: str, expected_version: int, reason_code: str
    ) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if (
                handoff is None
                or handoff.status != "BLOCKED_BINDING"
                or handoff.version != expected_version
            ):
                return False
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, reason_code
            )
            unit_of_work.commit()
            return True

    def _supersede_if_matching(
        self, handoff_id: str, expected_version: int, fingerprint: str, recovery_reason: str
    ) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if (
                handoff is None
                or handoff.status != "BLOCKED_BINDING"
                or handoff.version != expected_version
            ):
                return False
            run = unit_of_work.runs.get(handoff.execution.run_id)
            if run is None or run.status is not RunStatusV1.RECOVERY_REQUIRED:
                return False
            context = unit_of_work.recovery_contexts.load_current_context(handoff.execution.run_id)
            if (
                context is None
                or context["reason"] != recovery_reason
                or context.get("recovery_fingerprint") != fingerprint
            ):
                # Fail closed: a different (or non-matching) current Recovery authority
                # governs this run -- never overwrite it merely to retire the handoff.
                return False
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, _CHECKPOINT_MISMATCH_RECOVERED
            )
            unit_of_work.commit()
            return True


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
