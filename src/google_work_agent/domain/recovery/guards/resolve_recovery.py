"""Guards shared by the Recovery resolution transition."""

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


def guard_resolve_recovery(current_status: RunStatus) -> None:
    if current_status is not RunStatus.RECOVERY_REQUIRED:
        raise RunTransitionRejected("resolve_recovery requires RECOVERY_REQUIRED")
