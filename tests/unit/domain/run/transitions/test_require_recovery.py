import pytest
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.require_recovery import transition_require_recovery

def test_require_recovery_is_nonterminal_only():
    assert transition_require_recovery(RunStatus.VERIFYING) is RunStatus.RECOVERY_REQUIRED
    with pytest.raises(RunTransitionRejected):transition_require_recovery(RunStatus.CANCELLED)
