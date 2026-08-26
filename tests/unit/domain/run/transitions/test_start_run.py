import pytest

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.start_run import transition_start_run


def test_start_run_requires_no_open_run():
    assert transition_start_run(has_open_run=False) is RunStatus.CREATED
    with pytest.raises(RunTransitionRejected):
        transition_start_run(has_open_run=True)
