import pytest

from google_work_agent.domain.run.guards.start_analysis import guard_start_analysis
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_start_analysis_requires_created() -> None:
    guard_start_analysis(RunStatusV1.CREATED)
    with pytest.raises(RunTransitionRejected):
        guard_start_analysis(RunStatusV1.ANALYZING)
