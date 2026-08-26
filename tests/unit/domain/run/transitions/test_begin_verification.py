import pytest

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)


@pytest.mark.parametrize("source", [RunStatus.WAITING_APPROVAL, RunStatus.CANCEL_REQUESTED])
def test_begin_verification_exact_sources(source: RunStatus) -> None:
    assert transition_begin_verification(source) is RunStatus.VERIFYING


@pytest.mark.parametrize("source", [RunStatus.EXECUTING, RunStatus.REAUTH_REQUIRED])
def test_begin_verification_rejects_noncanonical_sources(source: RunStatus) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_verification(source)
