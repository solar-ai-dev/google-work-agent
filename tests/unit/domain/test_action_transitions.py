import pytest

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    EffectType,
    InvariantViolationError,
    ResultCode,
    VerificationStatus,
    next_allowed_action_commands,
    transition_action,
)


@pytest.mark.parametrize(
    ("effect_type", "current_status", "command", "next_status"),
    (
        (
            EffectType.CREATE,
            ActionStatus.PROPOSED,
            ActionCommand.APPROVE_ACTION,
            ActionStatus.APPROVED,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.MODIFIED,
            ActionCommand.APPROVE_ACTION,
            ActionStatus.APPROVED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.PROPOSED,
            ActionCommand.MODIFY_ACTION,
            ActionStatus.MODIFIED,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.APPROVED,
            ActionCommand.MODIFY_ACTION,
            ActionStatus.MODIFIED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.EXPIRED,
            ActionCommand.MODIFY_ACTION,
            ActionStatus.MODIFIED,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.FAILED,
            ActionCommand.MODIFY_ACTION,
            ActionStatus.MODIFIED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.PROPOSED,
            ActionCommand.REJECT_ACTION,
            ActionStatus.REJECTED,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.MODIFIED,
            ActionCommand.REJECT_ACTION,
            ActionStatus.REJECTED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.APPROVED,
            ActionCommand.EXPIRE_APPROVAL,
            ActionStatus.EXPIRED,
        ),
        (
            EffectType.READ,
            ActionStatus.PROPOSED,
            ActionCommand.CLAIM_READ_ACTION,
            ActionStatus.EXECUTING,
        ),
        (
            EffectType.READ,
            ActionStatus.EXECUTING,
            ActionCommand.COMPLETE_READ_ACTION,
            ActionStatus.EXECUTED,
        ),
        (
            EffectType.READ,
            ActionStatus.EXECUTED,
            ActionCommand.FINALIZE_READ_ACTION,
            ActionStatus.VERIFIED,
        ),
        (
            EffectType.READ,
            ActionStatus.EXECUTING,
            ActionCommand.FAIL_READ_ACTION,
            ActionStatus.FAILED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.APPROVED,
            ActionCommand.CLAIM_EXECUTION,
            ActionStatus.EXECUTING,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.EXECUTING,
            ActionCommand.STORE_SUCCESS,
            ActionStatus.EXECUTED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.EXECUTING,
            ActionCommand.MARK_FAILED,
            ActionStatus.FAILED,
        ),
        (
            EffectType.UPDATE,
            ActionStatus.EXECUTING,
            ActionCommand.MARK_UNKNOWN_RESULT,
            ActionStatus.UNKNOWN_RESULT,
        ),
        (
            EffectType.CREATE,
            ActionStatus.UNKNOWN_RESULT,
            ActionCommand.RECOVER_EXISTING_RESULT,
            ActionStatus.EXECUTED,
        ),
        (
            EffectType.CREATE,
            ActionStatus.FAILED,
            ActionCommand.PREPARE_WRITE_RETRY,
            ActionStatus.MODIFIED,
        ),
    ),
)
def test_allowed_action_edges(
    effect_type: EffectType,
    current_status: ActionStatus,
    command: ActionCommand,
    next_status: ActionStatus,
) -> None:
    result = transition_action(
        current_status,
        command,
        4,
        4,
        effect_type=effect_type,
        result_not_executed_confirmed=True,
    )

    assert result.applied is True
    assert result.result_code is ResultCode.TRANSITION_APPLIED
    assert result.current_status is next_status
    assert result.current_version == 5


def test_resolve_as_failed_requires_confirmation_flag() -> None:
    with pytest.raises(InvariantViolationError):
        transition_action(
            ActionStatus.UNKNOWN_RESULT,
            ActionCommand.RESOLVE_AS_FAILED,
            1,
            1,
            effect_type=EffectType.CREATE,
        )
    allowed = transition_action(
        ActionStatus.UNKNOWN_RESULT,
        ActionCommand.RESOLVE_AS_FAILED,
        1,
        1,
        effect_type=EffectType.CREATE,
        result_not_executed_confirmed=True,
    )

    assert allowed.applied is True
    assert allowed.current_status is ActionStatus.FAILED


@pytest.mark.parametrize(
    ("verification_status", "next_status"),
    (
        (VerificationStatus.VERIFIED, ActionStatus.VERIFIED),
        (VerificationStatus.MISMATCH, ActionStatus.MISMATCH),
    ),
)
def test_store_verification_terminal_results(
    verification_status: VerificationStatus,
    next_status: ActionStatus,
) -> None:
    result = transition_action(
        ActionStatus.EXECUTED,
        ActionCommand.STORE_VERIFICATION,
        3,
        3,
        effect_type=EffectType.UPDATE,
        verification_status=verification_status,
    )

    assert result.applied is True
    assert result.current_status is next_status
    assert result.current_version == 4


@pytest.mark.parametrize(
    "verification_status",
    (None, VerificationStatus.NOT_FOUND, VerificationStatus.ERROR),
)
def test_store_verification_non_final_results_do_not_transition(
    verification_status: VerificationStatus | None,
) -> None:
    with pytest.raises(InvariantViolationError):
        transition_action(
            ActionStatus.EXECUTED,
            ActionCommand.STORE_VERIFICATION,
            3,
            3,
            effect_type=EffectType.UPDATE,
            verification_status=verification_status,
        )


@pytest.mark.parametrize(
    ("effect_type", "current_status", "command"),
    (
        (EffectType.CREATE, ActionStatus.EXPIRED, ActionCommand.APPROVE_ACTION),
        (EffectType.CREATE, ActionStatus.FAILED, ActionCommand.CLAIM_EXECUTION),
        (EffectType.UPDATE, ActionStatus.UNKNOWN_RESULT, ActionCommand.CLAIM_EXECUTION),
        (EffectType.UPDATE, ActionStatus.UNKNOWN_RESULT, ActionCommand.STORE_SUCCESS),
        (EffectType.READ, ActionStatus.PROPOSED, ActionCommand.APPROVE_ACTION),
        (EffectType.READ, ActionStatus.PROPOSED, ActionCommand.CLAIM_EXECUTION),
        (EffectType.CREATE, ActionStatus.PROPOSED, ActionCommand.CLAIM_READ_ACTION),
        (EffectType.CREATE, ActionStatus.EXECUTED, ActionCommand.CLAIM_EXECUTION),
        (EffectType.CREATE, ActionStatus.MISMATCH, ActionCommand.CLAIM_EXECUTION),
        (EffectType.CREATE, ActionStatus.REJECTED, ActionCommand.APPROVE_ACTION),
        (EffectType.READ, ActionStatus.VERIFIED, ActionCommand.MODIFY_ACTION),
    ),
)
def test_explicitly_forbidden_action_edges(
    effect_type: EffectType,
    current_status: ActionStatus,
    command: ActionCommand,
) -> None:
    result = transition_action(
        current_status,
        command,
        2,
        2,
        effect_type=effect_type,
        result_not_executed_confirmed=True,
    )

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert result.current_status is current_status
    assert result.current_version == 2


def test_action_version_conflict_is_checked_before_transition() -> None:
    result = transition_action(
        ActionStatus.PROPOSED,
        ActionCommand.APPROVE_ACTION,
        3,
        2,
        effect_type=EffectType.CREATE,
    )

    assert result.applied is False
    assert result.result_code is ResultCode.VERSION_CONFLICT
    assert result.current_status is ActionStatus.PROPOSED
    assert result.current_version == 3


@pytest.mark.parametrize(
    ("current_version", "expected_version"),
    ((-1, -1), (1, -1)),
)
def test_action_negative_versions_are_blocked(
    current_version: int,
    expected_version: int,
) -> None:
    with pytest.raises(InvariantViolationError):
        transition_action(
            ActionStatus.PROPOSED,
            ActionCommand.APPROVE_ACTION,
            current_version,
            expected_version,
            effect_type=EffectType.CREATE,
        )


@pytest.mark.parametrize(
    ("status", "commands"),
    (
        (
            ActionStatus.PROPOSED,
            (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
                ActionCommand.CLAIM_READ_ACTION,
            ),
        ),
        (ActionStatus.MODIFIED, (ActionCommand.REJECT_ACTION,)),
        (ActionStatus.APPROVED, (ActionCommand.MODIFY_ACTION, ActionCommand.EXPIRE_APPROVAL)),
        (ActionStatus.REJECTED, ()),
        (ActionStatus.EXPIRED, (ActionCommand.MODIFY_ACTION,)),
        (
            ActionStatus.EXECUTING,
            (ActionCommand.COMPLETE_READ_ACTION, ActionCommand.FAIL_READ_ACTION),
        ),
        (ActionStatus.UNKNOWN_RESULT, ()),
        (ActionStatus.EXECUTED, (ActionCommand.FINALIZE_READ_ACTION,)),
        (ActionStatus.VERIFIED, ()),
        (ActionStatus.FAILED, (ActionCommand.MODIFY_ACTION,)),
        (ActionStatus.BLOCKED, ()),
        (ActionStatus.DEPENDENCY_BLOCKED, ()),
        (ActionStatus.MISMATCH, ()),
    ),
)
def test_next_allowed_read_action_commands(
    status: ActionStatus,
    commands: tuple[ActionCommand, ...],
) -> None:
    result = next_allowed_action_commands(status, effect_type=EffectType.READ)

    assert result == commands
    assert isinstance(result, tuple)
    assert len(result) == len(set(result))
    assert ActionCommand.APPROVE_ACTION not in result
    assert ActionCommand.CLAIM_EXECUTION not in result


@pytest.mark.parametrize(
    ("status", "commands"),
    (
        (
            ActionStatus.PROPOSED,
            (
                ActionCommand.APPROVE_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
            ),
        ),
        (ActionStatus.MODIFIED, (ActionCommand.APPROVE_ACTION, ActionCommand.REJECT_ACTION)),
        (
            ActionStatus.APPROVED,
            (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.EXPIRE_APPROVAL,
                ActionCommand.CLAIM_EXECUTION,
            ),
        ),
        (ActionStatus.REJECTED, ()),
        (ActionStatus.EXPIRED, (ActionCommand.MODIFY_ACTION,)),
        (
            ActionStatus.EXECUTING,
            (
                ActionCommand.STORE_SUCCESS,
                ActionCommand.MARK_FAILED,
                ActionCommand.MARK_UNKNOWN_RESULT,
            ),
        ),
        (
            ActionStatus.UNKNOWN_RESULT,
            (ActionCommand.RECOVER_EXISTING_RESULT, ActionCommand.RESOLVE_AS_FAILED),
        ),
        (ActionStatus.EXECUTED, (ActionCommand.STORE_VERIFICATION,)),
        (ActionStatus.VERIFIED, ()),
        (ActionStatus.FAILED, (ActionCommand.MODIFY_ACTION, ActionCommand.PREPARE_WRITE_RETRY)),
        (ActionStatus.BLOCKED, ()),
        (ActionStatus.DEPENDENCY_BLOCKED, ()),
        (ActionStatus.MISMATCH, ()),
    ),
)
def test_next_allowed_write_action_commands(
    status: ActionStatus,
    commands: tuple[ActionCommand, ...],
) -> None:
    result = next_allowed_action_commands(status, effect_type=EffectType.CREATE)

    assert result == commands
    assert isinstance(result, tuple)
    assert len(result) == len(set(result))
    assert ActionCommand.CLAIM_READ_ACTION not in result
