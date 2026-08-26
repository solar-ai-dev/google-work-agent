"""Enter verification for a write Run."""

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected

_ALLOWED = frozenset({RunStatus.WAITING_APPROVAL, RunStatus.CANCEL_REQUESTED})


def transition_begin_verification(current_status: RunStatus) -> RunStatus:
    if current_status not in _ALLOWED:
        raise RunTransitionRejected(f"BeginVerification is not allowed from {current_status.value}")
    return RunStatus.VERIFYING
