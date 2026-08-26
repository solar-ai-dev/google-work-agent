import pytest

from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.run.model import RunTransitionRejected


def test_require_recovery_applies_from_a_nonterminal_status() -> None:
    assert transition_require_recovery(RunStatus.VERIFYING) is RunStatus.RECOVERY_REQUIRED


@pytest.mark.parametrize(
    "status", (RunStatus.COMPLETED, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED)
)
def test_require_recovery_rejects_terminal_status(status: RunStatus) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_require_recovery(status)
