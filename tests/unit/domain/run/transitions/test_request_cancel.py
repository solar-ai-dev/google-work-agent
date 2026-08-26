import pytest

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.request_cancel import transition_request_cancel


def test_request_cancel_accepts_nonterminal_and_rejects_terminal():
    assert transition_request_cancel(RunStatus.PLANNING) is RunStatus.CANCEL_REQUESTED
    with pytest.raises(RunTransitionRejected):
        transition_request_cancel(RunStatus.COMPLETED)
