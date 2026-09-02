import pytest

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.start_run import transition_start_run


def test_start_run__requires_no__open_run() -> None:
    assert transition_start_run(has_open_run=False) is RunStatusV1.CREATED
    with pytest.raises(RunTransitionRejected):
        transition_start_run(has_open_run=True)
