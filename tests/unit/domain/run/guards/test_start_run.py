import pytest

from google_work_agent.domain.run.guards.start_run import guard_start_run
from google_work_agent.domain.run.model import RunTransitionRejected


def test_start_run__requires_no__open_conversation_run() -> None:
    guard_start_run(has_open_run=False)
    with pytest.raises(RunTransitionRejected):
        guard_start_run(has_open_run=True)
