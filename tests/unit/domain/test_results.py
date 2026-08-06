from dataclasses import FrozenInstanceError

import pytest

from google_work_agent.domain import CommandResult, ResultCode, RunCommand, RunStatus


def test_command_result_is_frozen() -> None:
    result: CommandResult[RunStatus, RunCommand] = CommandResult(
        applied=True,
        result_code=ResultCode.APPLIED,
        current_status=RunStatus.ANALYZING,
        current_version=1,
        next_allowed_commands=(RunCommand.BEGIN_RETRIEVAL,),
    )

    with pytest.raises(FrozenInstanceError):
        setattr(result, "applied", False)


def test_command_result_uses_tuple_for_next_allowed_commands() -> None:
    result: CommandResult[RunStatus, RunCommand] = CommandResult(
        applied=False,
        result_code=ResultCode.INVALID_TRANSITION,
        current_status=RunStatus.CREATED,
        current_version=0,
        next_allowed_commands=(RunCommand.START_ANALYSIS,),
        conflict_detail="not allowed",
    )

    assert isinstance(result.next_allowed_commands, tuple)
    assert result.conflict_detail == "not allowed"


def test_success_and_failure_result_fields() -> None:
    success: CommandResult[RunStatus, RunCommand] = CommandResult(
        applied=True,
        result_code=ResultCode.APPLIED,
        current_status=RunStatus.RETRIEVING,
        current_version=2,
        next_allowed_commands=(RunCommand.BEGIN_PLANNING,),
    )
    failure: CommandResult[RunStatus, RunCommand] = CommandResult(
        applied=False,
        result_code=ResultCode.VERSION_CONFLICT,
        current_status=RunStatus.RETRIEVING,
        current_version=1,
        next_allowed_commands=(RunCommand.BEGIN_PLANNING,),
        conflict_detail="expected_version does not match current_version",
    )

    assert success.applied is True
    assert success.result_code is ResultCode.APPLIED
    assert success.conflict_detail is None
    assert failure.applied is False
    assert failure.current_status is RunStatus.RETRIEVING
    assert failure.current_version == 1
