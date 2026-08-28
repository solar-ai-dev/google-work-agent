import pytest

from google_work_agent.domain.recovery.guards.resolve_recovery import guard_resolve_recovery
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_resolve_recovery_requires_recovery_required() -> None:
    guard_resolve_recovery(RunStatusV1.RECOVERY_REQUIRED)
    with pytest.raises(RunTransitionRejected):
        guard_resolve_recovery(RunStatusV1.VERIFYING)
