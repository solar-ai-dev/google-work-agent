from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus
from google_work_agent.domain.execution_attempt.transitions.recover_existing_result import (
    transition_recover_existing_result,
)


def test_recover_existing_result_requires_unknown_result_and_enters_verification() -> None:
    result = transition_recover_existing_result(
        ActionStatus.UNKNOWN_RESULT, current_version=1, expected_version=1
    )

    assert result.applied is True
    assert result.current_status is ActionStatus.EXECUTED
    assert result.next_allowed_commands == (ActionCommand.STORE_VERIFICATION,)
