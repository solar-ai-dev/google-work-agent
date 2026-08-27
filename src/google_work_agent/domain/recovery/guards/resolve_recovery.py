"""Guards shared by the Recovery resolution transition."""

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def guard_resolve_recovery(current_status: RunStatusV1) -> None:
    if current_status is not RunStatusV1.RECOVERY_REQUIRED:
        raise RunTransitionRejected("resolve_recovery requires RECOVERY_REQUIRED")
