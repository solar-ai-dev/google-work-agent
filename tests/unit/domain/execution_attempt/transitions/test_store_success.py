from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus
from google_work_agent.domain.execution_attempt.transitions.store_success import (
    transition_store_success,
)


def test_store_success_requires_executing_and_moves_to_executed() -> None:
    result = transition_store_success(ActionStatus.EXECUTING, current_version=3, expected_version=3)

    assert result.applied is True
    assert result.current_status is ActionStatus.EXECUTED
    assert result.next_allowed_commands == (ActionCommand.STORE_VERIFICATION,)
