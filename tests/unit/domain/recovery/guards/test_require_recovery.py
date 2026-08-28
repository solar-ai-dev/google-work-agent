import pytest

from google_work_agent.domain.recovery.guards.require_recovery import guard_require_recovery
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_require_recovery_accepts_nonterminal_and_rejects_terminal_run() -> None:
    guard_require_recovery(RunStatusV1.VERIFYING)
    with pytest.raises(RunTransitionRejected):
        guard_require_recovery(RunStatusV1.COMPLETED)
