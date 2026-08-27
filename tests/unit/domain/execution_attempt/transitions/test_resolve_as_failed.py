import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.resolve_as_failed import (
    transition_resolve_as_failed,
)
from google_work_agent.domain.results import InvariantViolationError


def test_resolve_as_failed_requires_confirmed_non_execution() -> None:
    with pytest.raises(InvariantViolationError):
        transition_resolve_as_failed(
            ActionStatusV1.UNKNOWN_RESULT,
            action_version=1,
            expected_action_version=1,
            attempt_status=ExecutionAttemptStatusV1.UNKNOWN_RESULT,
            attempt_version=2,
            expected_attempt_version=2,
            result_not_executed_confirmed=False,
        )
