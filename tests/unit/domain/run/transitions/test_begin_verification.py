import pytest

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)


@pytest.mark.parametrize("source", [RunStatusV1.WAITING_APPROVAL, RunStatusV1.CANCEL_REQUESTED])
def test_begin_verification__exact__sources(source: RunStatusV1) -> None:
    assert transition_begin_verification(source) is RunStatusV1.VERIFYING


@pytest.mark.parametrize("source", [RunStatusV1.EXECUTING, RunStatusV1.REAUTH_REQUIRED])
def test_begin_verification__rejects_noncanonical__sources(source: RunStatusV1) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_verification(source)
