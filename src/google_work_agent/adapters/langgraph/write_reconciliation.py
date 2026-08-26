"""Deterministic routing for write-domain reconciliation conflicts.

This module does not mutate Domain state. It translates already-persisted
aggregate facts into an existing LangGraph destination so callers never
retry a failed command speculatively.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.run.model import RunStatus


class ReconcileAggregate(StrEnum):
    ACTION = "ACTION"
    RUN = "RUN"


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    target: str
    outcome: str


_ACTION_APPROVAL_COMMANDS = frozenset({"APPROVE_ACTION"})
_ACTION_RECOVERY_STATUSES = frozenset(
    {
        ActionStatus.UNKNOWN_RESULT,
        ActionStatus.MISMATCH,
        ActionStatus.EXECUTED,
    }
)
_ACTION_TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.VERIFIED,
        ActionStatus.FAILED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.CANCELLED,
        ActionStatus.REJECTED,
    }
)
_RUN_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    }
)


def reconcile_write_conflict(
    *,
    aggregate: ReconcileAggregate,
    current_status: str | None,
    next_allowed_commands: tuple[str, ...],
) -> ReconciliationDecision:
    """Return one existing graph destination from authoritative persisted facts.

    ``end`` is used only for a real suspend/terminal branch. No command is
    automatically replayed here.
    """

    commands = frozenset(next_allowed_commands)
    if aggregate is ReconcileAggregate.ACTION:
        try:
            status = ActionStatus(current_status or "")
        except ValueError:
            return ReconciliationDecision(target="end", outcome="SUSPEND_CONTRACT_CONFLICT")

        if status in _ACTION_RECOVERY_STATUSES:
            return ReconciliationDecision(target="recovery", outcome="RECOVERY_REQUIRED")
        if status in _ACTION_TERMINAL_STATUSES:
            return ReconciliationDecision(
                target="action_execution",
                outcome="ALREADY_TERMINAL",
            )
        if commands & _ACTION_APPROVAL_COMMANDS or status in {
            ActionStatus.PROPOSED,
            ActionStatus.MODIFIED,
            ActionStatus.EXPIRED,
        }:
            return ReconciliationDecision(
                target="waiting_approval",
                outcome="WAITING_APPROVAL",
            )
        return ReconciliationDecision(target="end", outcome="SUSPEND_IN_FLIGHT")

    try:
        run_status = RunStatus(current_status or "")
    except ValueError:
        return ReconciliationDecision(target="end", outcome="SUSPEND_CONTRACT_CONFLICT")

    if run_status is RunStatus.WAITING_APPROVAL:
        return ReconciliationDecision(target="waiting_approval", outcome="WAITING_APPROVAL")
    if run_status is RunStatus.RECOVERY_REQUIRED or "RESOLVE_RECOVERY" in commands:
        return ReconciliationDecision(target="recovery", outcome="RECOVERY_REQUIRED")
    if run_status in _RUN_TERMINAL_STATUSES:
        return ReconciliationDecision(target="end", outcome="ALREADY_TERMINAL")
    if run_status is RunStatus.REAUTH_REQUIRED:
        return ReconciliationDecision(target="end", outcome="SUSPEND_REAUTH_REQUIRED")
    if run_status is RunStatus.CANCEL_REQUESTED:
        return ReconciliationDecision(target="end", outcome="SUSPEND_CANCEL_REQUESTED")
    return ReconciliationDecision(target="end", outcome="SUSPEND_IN_FLIGHT")


__all__ = [
    "ReconcileAggregate",
    "ReconciliationDecision",
    "reconcile_write_conflict",
]
