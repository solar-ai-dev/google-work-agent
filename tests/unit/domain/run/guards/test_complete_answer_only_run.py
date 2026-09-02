import pytest

from google_work_agent.domain.run.guards.complete_answer_only_run import (
    guard_complete_answer_only_run,
)
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_answer_only__completion_requires_no__persisted_work_facts() -> None:
    guard_complete_answer_only_run(
        RunStatusV1.ANALYZING,
        has_plan=False,
        has_action=False,
        has_open_write=False,
        has_executing_read=False,
        has_unresolved_recovery=False,
    )
    with pytest.raises(RunTransitionRejected):
        guard_complete_answer_only_run(
            RunStatusV1.ANALYZING,
            has_plan=True,
            has_action=False,
            has_open_write=False,
            has_executing_read=False,
            has_unresolved_recovery=False,
        )
