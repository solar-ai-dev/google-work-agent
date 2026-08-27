"""Enter verification for a write Run."""

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected

_ALLOWED = frozenset({RunStatusV1.WAITING_APPROVAL, RunStatusV1.CANCEL_REQUESTED})


def transition_begin_verification(current_status: RunStatusV1) -> RunStatusV1:
    if current_status not in _ALLOWED:
        raise RunTransitionRejected(f"BeginVerification is not allowed from {current_status.value}")
    return RunStatusV1.VERIFYING
