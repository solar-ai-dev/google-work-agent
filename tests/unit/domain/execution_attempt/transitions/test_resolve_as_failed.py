import pytest

from google_work_agent.domain.enums import ActionStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.execution_attempt.transitions.resolve_as_failed import (
    transition_resolve_as_failed,
)


def test_resolve_as_failed_requires_confirmed_non_execution() -> None:
    with pytest.raises(InvariantViolationError):
        transition_resolve_as_failed(
            ActionStatus.UNKNOWN_RESULT,
            current_version=1,
            expected_version=1,
            result_not_executed_confirmed=False,
        )
