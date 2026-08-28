import pytest

from google_work_agent.domain.run.guards.begin_retrieval import guard_begin_retrieval
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_begin_retrieval_accepts_source_phases_only() -> None:
    guard_begin_retrieval(RunStatusV1.ANALYZING)
    guard_begin_retrieval(RunStatusV1.PLANNING)
    with pytest.raises(RunTransitionRejected):
        guard_begin_retrieval(RunStatusV1.CREATED)
