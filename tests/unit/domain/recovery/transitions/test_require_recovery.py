import pytest

from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_require_recovery_applies_from_a_nonterminal_status() -> None:
    assert transition_require_recovery(RunStatusV1.VERIFYING) is RunStatusV1.RECOVERY_REQUIRED


@pytest.mark.parametrize(
    "status",
    (RunStatusV1.COMPLETED, RunStatusV1.BLOCKED, RunStatusV1.FAILED, RunStatusV1.CANCELLED),
)
def test_require_recovery_rejects_terminal_status(status: RunStatusV1) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_require_recovery(status)
