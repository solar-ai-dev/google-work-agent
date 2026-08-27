import pytest

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.complete_answer_only_run import (
    transition_complete_answer_only_run,
)


def test_complete_answer_only_run_applies_canonical_transition():
    assert transition_complete_answer_only_run(RunStatusV1.ANALYZING) is RunStatusV1.COMPLETED


def test_complete_answer_only_run_rejects_unrelated_status():
    try:
        transition_complete_answer_only_run(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")


def test_complete_answer_only_run_rejects_child_authority() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_complete_answer_only_run(RunStatusV1.ANALYZING, has_plan=True)
