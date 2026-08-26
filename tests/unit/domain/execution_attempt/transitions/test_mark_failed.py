import pytest

from google_work_agent.domain.enums import ActionStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.execution_attempt.transitions.mark_failed import (
    transition_mark_failed,
)


def test_mark_failed_requires_not_sent_delivery_certainty() -> None:
    with pytest.raises(InvariantViolationError):
        transition_mark_failed(
            ActionStatus.EXECUTING,
            current_version=0,
            expected_version=0,
            delivery_certainty="MAY_HAVE_BEEN_SENT",
        )
