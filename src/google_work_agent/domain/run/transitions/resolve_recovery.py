"""Canonical explicit recovery-resolution transition."""
from google_work_agent.domain.enums import RecoveryResolution, RunStatus
from google_work_agent.domain.run.guards.resolve_recovery import guard_resolve_recovery

_TARGETS = {
    RecoveryResolution.RECHECK: RunStatus.VERIFYING,
    RecoveryResolution.ACCEPT_PARTIAL: RunStatus.COMPLETED,
    RecoveryResolution.CREATE_CORRECTIVE_PLAN: RunStatus.PLANNING,
    RecoveryResolution.CANCEL: RunStatus.CANCELLED,
    RecoveryResolution.FAIL: RunStatus.FAILED,
}

def transition_resolve_recovery(
    current_status: RunStatus,
    *,
    resolution: RecoveryResolution,
    cancel_intent_active: bool = False,
    terminal_snapshot: bool = False,
    irrecoverable_confirmed: bool = False,
) -> RunStatus:
    guard_resolve_recovery(
        current_status,
        resolution=resolution,
        cancel_intent_active=cancel_intent_active,
        terminal_snapshot=terminal_snapshot,
        irrecoverable_confirmed=irrecoverable_confirmed,
    )
    return _TARGETS[resolution]
