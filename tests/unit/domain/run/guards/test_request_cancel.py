import pytest

from google_work_agent.domain.run.guards.request_cancel import guard_request_cancel
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_request_cancel__accepts_nonterminal_and__rejects_terminal_run() -> None:
    guard_request_cancel(RunStatusV1.EXECUTING)
    with pytest.raises(RunTransitionRejected):
        guard_request_cancel(RunStatusV1.CANCELLED)
