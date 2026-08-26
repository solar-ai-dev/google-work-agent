"""Canonical BLOCKED_BINDING handoff reconciliation (08-sequence-design.md).

Deterministic sequence: BLOCKED_BINDING dispatch head -> deterministic
RequireRecovery(CHECKPOINT_MISMATCH) -> matching RecoveryContext confirmed ->
handoff SUPERSEDED. This module owns only the reconciliation *sequence*; the
Run transition + durable RecoveryContextV1 write remain owned exclusively by
``RequireRecoveryHandler``, and resume-target/binding legality remains owned
exclusively by ``ResumeTargetRegistry`` (consumed indirectly, never
duplicated here).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from google_work_agent.application.use_cases.run.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import TERMINAL_RUN_STATUSES
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import WorkflowHandoffV1

_RUN_NOT_EXECUTABLE = "RUN_NOT_EXECUTABLE"
_CHECKPOINT_MISMATCH_RECOVERED = "CHECKPOINT_MISMATCH_RECOVERED"


@dataclass(frozen=True, slots=True)
class ReconcileBlockedBindingCommand:
    handoff_id: str


@dataclass(frozen=True, slots=True)
class ReconcileBlockedBindingResult:
    handoff_id: str
    outcome: Literal[
        "NOT_FOUND",
        "RUN_NOT_EXECUTABLE",
        "PREEMPTED_BY_OTHER_AUTHORITY",
        "RECOVERY_NOT_APPLIED",
        "RECOVERY_PENDING",
        "RECOVERED",
        "NOT_MATCHING_RECOVERY_CONTEXT",
    ]


class ReconcileBlockedBindingHandler:
    """Reconcile one BLOCKED_BINDING handoff into a durable CHECKPOINT_MISMATCH recovery."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        require_recovery: RequireRecoveryHandler,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._require_recovery = require_recovery

    def __call__(self, command: ReconcileBlockedBindingCommand) -> ReconcileBlockedBindingResult:
        handoff_id = command.handoff_id
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return ReconcileBlockedBindingResult(handoff_id, "NOT_FOUND")
            run = unit_of_work.runs.get_by_id(handoff.execution.run_id)

        if run is None:
            return ReconcileBlockedBindingResult(handoff_id, "NOT_FOUND")

        if run.status in TERMINAL_RUN_STATUSES:
            self._supersede_if_still_blocked(handoff_id, _RUN_NOT_EXECUTABLE)
            return ReconcileBlockedBindingResult(handoff_id, "RUN_NOT_EXECUTABLE")

        if run.status in {RunStatus.REAUTH_REQUIRED, RunStatus.CANCEL_REQUESTED}:
            # A different Domain authority already governs this run -- never create a
            # competing CHECKPOINT_MISMATCH recovery merely to retire the handoff.
            return ReconcileBlockedBindingResult(handoff_id, "PREEMPTED_BY_OTHER_AUTHORITY")

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
                return ReconcileBlockedBindingResult(handoff_id, "RECOVERY_NOT_APPLIED")

        return self._supersede_if_matching(handoff_id, fingerprint)

    def _supersede_if_still_blocked(self, handoff_id: str, reason_code: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, reason_code
            )
            unit_of_work.commit()

    def _supersede_if_matching(
        self, handoff_id: str, fingerprint: str
    ) -> ReconcileBlockedBindingResult:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(handoff_id)
            if handoff is None or handoff.status != "BLOCKED_BINDING":
                return ReconcileBlockedBindingResult(handoff_id, "NOT_FOUND")
            run = unit_of_work.runs.get_by_id(handoff.execution.run_id)
            if run is None or run.status is not RunStatus.RECOVERY_REQUIRED:
                return ReconcileBlockedBindingResult(handoff_id, "RECOVERY_PENDING")
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
                return ReconcileBlockedBindingResult(handoff_id, "NOT_MATCHING_RECOVERY_CONTEXT")
            unit_of_work.workflow_handoffs.mark_superseded(
                handoff.handoff_id, handoff.version, _CHECKPOINT_MISMATCH_RECOVERED
            )
            unit_of_work.commit()
            return ReconcileBlockedBindingResult(handoff_id, "RECOVERED")


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


__all__ = [
    "ReconcileBlockedBindingCommand",
    "ReconcileBlockedBindingHandler",
    "ReconcileBlockedBindingResult",
]
