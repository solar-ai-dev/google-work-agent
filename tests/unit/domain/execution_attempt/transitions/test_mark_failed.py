import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.mark_failed import (
    transition_mark_failed,
)
from google_work_agent.domain.results import InvariantViolationError


def test_mark_failed__requires_not__sent_delivery_certainty() -> None:
    with pytest.raises(InvariantViolationError):
        transition_mark_failed(
            ActionStatusV1.EXECUTING,
            action_version=0,
            expected_action_version=0,
            attempt_status=ExecutionAttemptStatusV1.EXECUTING,
            attempt_version=0,
            expected_attempt_version=0,
            delivery_certainty="MAY_HAVE_BEEN_SENT",
        )
