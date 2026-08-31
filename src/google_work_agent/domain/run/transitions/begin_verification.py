"""Enter verification for a write Run."""

from google_work_agent.domain.run.guards.begin_verification import guard_begin_verification
from google_work_agent.domain.run.model import RunStatusV1


def transition_begin_verification(current_status: RunStatusV1) -> RunStatusV1:
    guard_begin_verification(current_status)
    return RunStatusV1.VERIFYING
