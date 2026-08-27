from dataclasses import FrozenInstanceError

import pytest

from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatusV1


def test_command_result_is_frozen() -> None:
    result: CommandResult[RunStatusV1, RunCommand] = CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=RunStatusV1.ANALYZING,
        current_version=1,
        next_allowed_commands=(RunCommand.BEGIN_RETRIEVAL,),
    )

    with pytest.raises(FrozenInstanceError):
        result.applied = False  # type: ignore[misc]


def test_command_result_uses_tuple_for_next_allowed_commands() -> None:
    result: CommandResult[RunStatusV1, RunCommand] = CommandResult(
        applied=False,
        result_code=ResultCode.STATE_CONFLICT,
        current_status=RunStatusV1.CREATED,
        current_version=0,
        next_allowed_commands=(RunCommand.START_ANALYSIS,),
        conflict_detail="not allowed",
    )

    assert isinstance(result.next_allowed_commands, tuple)
    assert result.conflict_detail == "not allowed"


def test_success_and_failure_result_fields() -> None:
    success: CommandResult[RunStatusV1, RunCommand] = CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=RunStatusV1.RETRIEVING,
        current_version=2,
        next_allowed_commands=(RunCommand.BEGIN_PLANNING,),
    )
    failure: CommandResult[RunStatusV1, RunCommand] = CommandResult(
        applied=False,
        result_code=ResultCode.VERSION_CONFLICT,
        current_status=RunStatusV1.RETRIEVING,
        current_version=1,
        next_allowed_commands=(RunCommand.BEGIN_PLANNING,),
        conflict_detail="expected_version does not match current_version",
    )

    assert success.applied is True
    assert success.result_code is ResultCode.TRANSITION_APPLIED
    assert success.conflict_detail is None
    assert failure.applied is False
    assert failure.current_status is RunStatusV1.RETRIEVING
    assert failure.current_version == 1
