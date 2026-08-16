import pytest

from google_work_agent.domain import (
    InvariantViolationError,
    ResultCode,
    RunCommand,
    RunStatus,
    next_allowed_run_commands,
    transition_run,
)


@pytest.mark.parametrize(
    ("current_status", "command", "next_status"),
    (
        (RunStatus.CREATED, RunCommand.START_ANALYSIS, RunStatus.ANALYZING),
        (RunStatus.ANALYZING, RunCommand.BEGIN_RETRIEVAL, RunStatus.RETRIEVING),
        (
            RunStatus.WAITING_CONFIRMATION,
            RunCommand.BEGIN_RETRIEVAL,
            RunStatus.RETRIEVING,
        ),
        (RunStatus.RETRIEVING, RunCommand.BEGIN_PLANNING, RunStatus.PLANNING),
        (
            RunStatus.ANALYZING,
            RunCommand.REQUEST_CONFIRMATION,
            RunStatus.WAITING_CONFIRMATION,
        ),
        (
            RunStatus.RETRIEVING,
            RunCommand.REQUEST_CONFIRMATION,
            RunStatus.WAITING_CONFIRMATION,
        ),
        (
            RunStatus.PLANNING,
            RunCommand.REQUEST_CONFIRMATION,
            RunStatus.WAITING_CONFIRMATION,
        ),
        (RunStatus.ANALYZING, RunCommand.BLOCK_RUN, RunStatus.BLOCKED),
        (RunStatus.RETRIEVING, RunCommand.BLOCK_RUN, RunStatus.BLOCKED),
        (RunStatus.PLANNING, RunCommand.BLOCK_RUN, RunStatus.BLOCKED),
        (RunStatus.WAITING_APPROVAL, RunCommand.BLOCK_RUN, RunStatus.BLOCKED),
        (RunStatus.WAITING_APPROVAL, RunCommand.REPLAN, RunStatus.PLANNING),
        (RunStatus.ANALYZING, RunCommand.FAIL_RUN, RunStatus.FAILED),
        (RunStatus.RETRIEVING, RunCommand.FAIL_RUN, RunStatus.FAILED),
        (RunStatus.PLANNING, RunCommand.FAIL_RUN, RunStatus.FAILED),
        (RunStatus.ANALYZING, RunCommand.COMPLETE_ANSWER_ONLY_RUN, RunStatus.COMPLETED),
        (RunStatus.RETRIEVING, RunCommand.COMPLETE_ANSWER_ONLY_RUN, RunStatus.COMPLETED),
        (RunStatus.PLANNING, RunCommand.COMPLETE_ANSWER_ONLY_RUN, RunStatus.COMPLETED),
        (RunStatus.CREATED, RunCommand.REQUEST_CANCEL, RunStatus.CANCEL_REQUESTED),
        (RunStatus.EXECUTING, RunCommand.REQUEST_CANCEL, RunStatus.CANCEL_REQUESTED),
        (RunStatus.CANCEL_REQUESTED, RunCommand.FINALIZE_CANCEL, RunStatus.CANCELLED),
        (RunStatus.RETRIEVING, RunCommand.REQUIRE_REAUTH, RunStatus.REAUTH_REQUIRED),
        (RunStatus.WAITING_APPROVAL, RunCommand.REQUIRE_REAUTH, RunStatus.REAUTH_REQUIRED),
        (RunStatus.EXECUTING, RunCommand.REQUIRE_REAUTH, RunStatus.REAUTH_REQUIRED),
        (RunStatus.VERIFYING, RunCommand.REQUIRE_REAUTH, RunStatus.REAUTH_REQUIRED),
        (RunStatus.EXECUTING, RunCommand.BEGIN_VERIFICATION, RunStatus.VERIFYING),
        (RunStatus.WAITING_APPROVAL, RunCommand.BEGIN_VERIFICATION, RunStatus.VERIFYING),
        (RunStatus.CANCEL_REQUESTED, RunCommand.BEGIN_VERIFICATION, RunStatus.VERIFYING),
        (RunStatus.REAUTH_REQUIRED, RunCommand.BEGIN_VERIFICATION, RunStatus.VERIFYING),
        (RunStatus.EXECUTING, RunCommand.REQUIRE_RECOVERY, RunStatus.RECOVERY_REQUIRED),
        (RunStatus.RECOVERY_REQUIRED, RunCommand.RESOLVE_RECOVERY, RunStatus.VERIFYING),
        (
            RunStatus.WAITING_APPROVAL,
            RunCommand.FINALIZE_ACTION_OUTCOMES,
            RunStatus.COMPLETED,
        ),
        (RunStatus.EXECUTING, RunCommand.FINALIZE_ACTION_OUTCOMES, RunStatus.COMPLETED),
        (RunStatus.VERIFYING, RunCommand.FINALIZE_ACTION_OUTCOMES, RunStatus.COMPLETED),
    ),
)
def test_allowed_run_edges(
    current_status: RunStatus,
    command: RunCommand,
    next_status: RunStatus,
) -> None:
    result = transition_run(
        current_status,
        command,
        7,
        7,
        recovery_next_status=RunStatus.VERIFYING
        if command is RunCommand.RESOLVE_RECOVERY
        else None,
    )

    assert result.applied is True
    assert result.result_code is ResultCode.TRANSITION_APPLIED
    assert result.current_status is next_status
    assert result.current_version == 8


@pytest.mark.parametrize(
    ("plan_requires_approval", "next_status"),
    ((True, RunStatus.WAITING_APPROVAL), (False, RunStatus.EXECUTING)),
)
def test_publish_plan_branches(
    plan_requires_approval: bool,
    next_status: RunStatus,
) -> None:
    result = transition_run(
        RunStatus.PLANNING,
        RunCommand.PUBLISH_PLAN,
        2,
        2,
        plan_requires_approval=plan_requires_approval,
    )

    assert result.applied is True
    assert result.current_status is next_status
    assert result.current_version == 3


def test_publish_plan_requires_explicit_branch() -> None:
    with pytest.raises(InvariantViolationError):
        transition_run(RunStatus.PLANNING, RunCommand.PUBLISH_PLAN, 2, 2)


def test_resolve_recovery_requires_explicit_status() -> None:
    with pytest.raises(InvariantViolationError):
        transition_run(RunStatus.RECOVERY_REQUIRED, RunCommand.RESOLVE_RECOVERY, 2, 2)


@pytest.mark.parametrize(
    "next_status",
    (
        RunStatus.VERIFYING,
        RunStatus.PLANNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ),
)
def test_resolve_recovery_allowed_targets(next_status: RunStatus) -> None:
    result = transition_run(
        RunStatus.RECOVERY_REQUIRED,
        RunCommand.RESOLVE_RECOVERY,
        2,
        2,
        recovery_next_status=next_status,
    )

    assert result.applied is True
    assert result.current_status is next_status
    assert result.current_version == 3


def test_run_version_conflict_is_checked_before_transition() -> None:
    result = transition_run(RunStatus.CREATED, RunCommand.START_ANALYSIS, 3, 2)

    assert result.applied is False
    assert result.result_code is ResultCode.VERSION_CONFLICT
    assert result.current_status is RunStatus.CREATED
    assert result.current_version == 3
    assert result.next_allowed_commands == (
        RunCommand.START_ANALYSIS,
        RunCommand.REQUEST_CANCEL,
        RunCommand.REQUIRE_RECOVERY,
    )


@pytest.mark.parametrize(
    ("current_version", "expected_version"),
    ((-1, -1), (1, -1)),
)
def test_run_negative_versions_are_blocked(
    current_version: int,
    expected_version: int,
) -> None:
    with pytest.raises(InvariantViolationError):
        transition_run(
            RunStatus.CREATED,
            RunCommand.START_ANALYSIS,
            current_version,
            expected_version,
        )


@pytest.mark.parametrize("terminal_status", (RunStatus.COMPLETED, RunStatus.CANCELLED))
def test_terminal_run_status_blocks_commands(terminal_status: RunStatus) -> None:
    command = (
        RunCommand.REQUEST_CANCEL
        if terminal_status is RunStatus.COMPLETED
        else RunCommand.START_ANALYSIS
    )
    result = transition_run(terminal_status, command, 1, 1)

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert result.next_allowed_commands == ()


@pytest.mark.parametrize(
    ("status", "command"),
    (
        (RunStatus.WAITING_CONFIRMATION, RunCommand.BLOCK_RUN),
        (RunStatus.EXECUTING, RunCommand.BLOCK_RUN),
        (RunStatus.VERIFYING, RunCommand.BLOCK_RUN),
        (RunStatus.EXECUTING, RunCommand.FAIL_RUN),
        (RunStatus.VERIFYING, RunCommand.FAIL_RUN),
        (RunStatus.ANALYZING, RunCommand.REQUIRE_REAUTH),
        (RunStatus.PLANNING, RunCommand.REQUIRE_REAUTH),
    ),
)
def test_new_run_commands_reject_out_of_scope_statuses(
    status: RunStatus,
    command: RunCommand,
) -> None:
    result = transition_run(status, command, 1, 1)

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert command not in result.next_allowed_commands


def test_cancel_requested_self_transition_is_blocked() -> None:
    result = transition_run(RunStatus.CANCEL_REQUESTED, RunCommand.REQUEST_CANCEL, 1, 1)

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert result.current_status is RunStatus.CANCEL_REQUESTED


@pytest.mark.parametrize(
    ("status", "commands"),
    (
        (
            RunStatus.CREATED,
            (
                RunCommand.START_ANALYSIS,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.ANALYZING,
            (
                RunCommand.BEGIN_RETRIEVAL,
                RunCommand.REQUEST_CONFIRMATION,
                RunCommand.BLOCK_RUN,
                RunCommand.FAIL_RUN,
                RunCommand.COMPLETE_ANSWER_ONLY_RUN,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.RETRIEVING,
            (
                RunCommand.BEGIN_PLANNING,
                RunCommand.REQUEST_CONFIRMATION,
                RunCommand.BLOCK_RUN,
                RunCommand.FAIL_RUN,
                RunCommand.COMPLETE_ANSWER_ONLY_RUN,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_REAUTH,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.WAITING_CONFIRMATION,
            (
                RunCommand.BEGIN_RETRIEVAL,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.PLANNING,
            (
                RunCommand.REQUEST_CONFIRMATION,
                RunCommand.BLOCK_RUN,
                RunCommand.FAIL_RUN,
                RunCommand.PUBLISH_PLAN,
                RunCommand.COMPLETE_ANSWER_ONLY_RUN,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.WAITING_APPROVAL,
            (
                RunCommand.BEGIN_VERIFICATION,
                RunCommand.BLOCK_RUN,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_REAUTH,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.EXECUTING,
            (
                RunCommand.BEGIN_VERIFICATION,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_REAUTH,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.VERIFYING,
            (
                RunCommand.COMPLETE_WRITE_RUN,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_REAUTH,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (
            RunStatus.CANCEL_REQUESTED,
            (
                RunCommand.BEGIN_VERIFICATION,
                RunCommand.FINALIZE_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (RunStatus.COMPLETED, ()),
        (RunStatus.CANCELLED, ()),
        (
            RunStatus.REAUTH_REQUIRED,
            (
                RunCommand.BEGIN_VERIFICATION,
                RunCommand.REQUEST_CANCEL,
                RunCommand.REQUIRE_RECOVERY,
            ),
        ),
        (RunStatus.RECOVERY_REQUIRED, (RunCommand.REQUEST_CANCEL, RunCommand.RESOLVE_RECOVERY)),
        (RunStatus.FAILED, ()),
        (RunStatus.BLOCKED, ()),
    ),
)
def test_next_allowed_run_commands(status: RunStatus, commands: tuple[RunCommand, ...]) -> None:
    result = next_allowed_run_commands(status)

    assert result == commands
    assert isinstance(result, tuple)
    assert len(result) == len(set(result))
