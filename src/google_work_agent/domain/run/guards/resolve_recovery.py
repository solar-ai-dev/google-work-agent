"""Guards for explicit recovery resolution."""
from google_work_agent.domain.enums import RecoveryResolution, RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected

def guard_resolve_recovery(
    current_status: RunStatus,
    *,
    resolution: RecoveryResolution,
    cancel_intent_active: bool = False,
    terminal_snapshot: bool = False,
    irrecoverable_confirmed: bool = False,
) -> None:
    if current_status is not RunStatus.RECOVERY_REQUIRED:
        raise RunTransitionRejected("resolve_recovery requires RECOVERY_REQUIRED")
    if resolution in {RecoveryResolution.ACCEPT_PARTIAL, RecoveryResolution.CREATE_CORRECTIVE_PLAN} and cancel_intent_active:
        raise RunTransitionRejected(f"{resolution.value} is forbidden while cancel intent is active")
    if resolution is RecoveryResolution.CANCEL and not (cancel_intent_active and terminal_snapshot):
        raise RunTransitionRejected("CANCEL requires durable cancel intent and a terminal snapshot")
    if resolution is RecoveryResolution.FAIL and not irrecoverable_confirmed:
        raise RunTransitionRejected("FAIL requires irrecoverable recovery failure to be confirmed")
