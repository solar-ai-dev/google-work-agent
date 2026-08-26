from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus
from google_work_agent.domain.execution_attempt.transitions.mark_unknown_result import (
    transition_mark_unknown_result,
)


def test_mark_unknown_result_does_not_offer_direct_retry() -> None:
    result = transition_mark_unknown_result(
        ActionStatus.EXECUTING, current_version=0, expected_version=0
    )

    assert result.current_status is ActionStatus.UNKNOWN_RESULT
    assert ActionCommand.PREPARE_WRITE_RETRY not in result.next_allowed_commands
