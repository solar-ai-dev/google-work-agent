"""Pure Python domain status transition functions."""

from google_work_agent.domain.commands import ActionCommand, RunCommand
from google_work_agent.domain.enums import (
    ActionStatus,
    EffectType,
    ResultCode,
    RunStatus,
    VerificationStatus,
)
from google_work_agent.domain.errors import InvariantViolationError
from google_work_agent.domain.results import CommandResult

RUN_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    }
)

ACTION_TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.REJECTED,
        ActionStatus.VERIFIED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.MISMATCH,
    }
)

WRITE_EFFECTS = frozenset(
    {
        EffectType.CREATE,
        EffectType.UPDATE,
        EffectType.SEND,
        EffectType.DELETE,
    }
)

RUN_TRANSITIONS: dict[tuple[RunStatus, RunCommand], RunStatus] = {
    (RunStatus.CREATED, RunCommand.START_ANALYSIS): RunStatus.ANALYZING,
    (RunStatus.ANALYZING, RunCommand.BEGIN_RETRIEVAL): RunStatus.RETRIEVING,
    (RunStatus.WAITING_CONFIRMATION, RunCommand.BEGIN_RETRIEVAL): RunStatus.RETRIEVING,
    (RunStatus.RETRIEVING, RunCommand.BEGIN_PLANNING): RunStatus.PLANNING,
    (RunStatus.ANALYZING, RunCommand.REQUEST_CONFIRMATION): RunStatus.WAITING_CONFIRMATION,
    (RunStatus.RETRIEVING, RunCommand.REQUEST_CONFIRMATION): RunStatus.WAITING_CONFIRMATION,
    (RunStatus.PLANNING, RunCommand.REQUEST_CONFIRMATION): RunStatus.WAITING_CONFIRMATION,
    (RunStatus.ANALYZING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.RETRIEVING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.PLANNING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.ANALYZING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.RETRIEVING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.PLANNING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.ANALYZING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.RETRIEVING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.PLANNING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.CANCEL_REQUESTED, RunCommand.FINALIZE_CANCEL): RunStatus.CANCELLED,
    (RunStatus.RETRIEVING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
}

RUN_COMMAND_ORDER = tuple(RunCommand)
ACTION_COMMAND_ORDER = tuple(ActionCommand)

READ_ACTION_TRANSITIONS: dict[tuple[ActionStatus, ActionCommand], ActionStatus] = {
    (ActionStatus.PROPOSED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.APPROVED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.EXPIRED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.FAILED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.PROPOSED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.MODIFIED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.APPROVED, ActionCommand.EXPIRE_APPROVAL): ActionStatus.EXPIRED,
    (ActionStatus.PROPOSED, ActionCommand.CLAIM_READ_ACTION): ActionStatus.EXECUTING,
    (ActionStatus.EXECUTING, ActionCommand.COMPLETE_READ_ACTION): ActionStatus.EXECUTED,
    (ActionStatus.EXECUTED, ActionCommand.FINALIZE_READ_ACTION): ActionStatus.VERIFIED,
    (ActionStatus.EXECUTING, ActionCommand.FAIL_READ_ACTION): ActionStatus.FAILED,
}

WRITE_ACTION_TRANSITIONS: dict[tuple[ActionStatus, ActionCommand], ActionStatus] = {
    (ActionStatus.PROPOSED, ActionCommand.APPROVE_ACTION): ActionStatus.APPROVED,
    (ActionStatus.MODIFIED, ActionCommand.APPROVE_ACTION): ActionStatus.APPROVED,
    (ActionStatus.PROPOSED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.APPROVED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.EXPIRED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.FAILED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.PROPOSED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.MODIFIED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.APPROVED, ActionCommand.EXPIRE_APPROVAL): ActionStatus.EXPIRED,
    (ActionStatus.APPROVED, ActionCommand.CLAIM_EXECUTION): ActionStatus.EXECUTING,
    (ActionStatus.EXECUTING, ActionCommand.STORE_SUCCESS): ActionStatus.EXECUTED,
    (ActionStatus.EXECUTING, ActionCommand.MARK_FAILED): ActionStatus.FAILED,
    (ActionStatus.EXECUTING, ActionCommand.MARK_UNKNOWN_RESULT): ActionStatus.UNKNOWN_RESULT,
    (ActionStatus.UNKNOWN_RESULT, ActionCommand.RECOVER_EXISTING_RESULT): ActionStatus.EXECUTED,
    (ActionStatus.UNKNOWN_RESULT, ActionCommand.RESOLVE_AS_FAILED): ActionStatus.FAILED,
    (ActionStatus.FAILED, ActionCommand.PREPARE_WRITE_RETRY): ActionStatus.MODIFIED,
}


def next_allowed_run_commands(current_status: RunStatus) -> tuple[RunCommand, ...]:
    """Return the deterministic Run commands allowed from the current status."""
    if current_status in RUN_TERMINAL_STATUSES:
        return ()

    commands = [
        command
        for command in RUN_COMMAND_ORDER
        if (current_status, command) in RUN_TRANSITIONS
        or _is_publish_plan_candidate(current_status, command)
        or _is_cancel_candidate(current_status, command)
        or _is_require_recovery_candidate(current_status, command)
        or _is_resolve_recovery_candidate(current_status, command)
    ]
    return tuple(dict.fromkeys(commands))


def next_allowed_action_commands(
    current_status: ActionStatus,
    *,
    effect_type: EffectType,
) -> tuple[ActionCommand, ...]:
    """Return deterministic Action commands allowed for the current status and effect."""
    if current_status in ACTION_TERMINAL_STATUSES:
        return ()

    transition_table = _action_transition_table(effect_type)
    commands = [
        command
        for command in ACTION_COMMAND_ORDER
        if (current_status, command) in transition_table
        or _is_store_verification_candidate(effect_type, current_status, command)
    ]
    return tuple(dict.fromkeys(commands))


def transition_run(
    current_status: RunStatus,
    command: RunCommand,
    current_version: int,
    expected_version: int,
    *,
    plan_requires_approval: bool | None = None,
    recovery_next_status: RunStatus | None = None,
) -> CommandResult[RunStatus, RunCommand]:
    """Apply a pure Run status transition with optimistic version checking."""
    if not _is_non_negative_version(current_version):
        raise InvariantViolationError("current_version must be non-negative")
    if not _is_non_negative_version(expected_version):
        raise InvariantViolationError("expected_version must be non-negative")
    if expected_version != current_version:
        return _run_failure(
            current_status,
            current_version,
            ResultCode.VERSION_CONFLICT,
            "expected_version does not match current_version",
        )

    if (
        current_status is RunStatus.PLANNING
        and command is RunCommand.PUBLISH_PLAN
        and plan_requires_approval is None
    ):
        raise InvariantViolationError("plan_requires_approval is required")
    if (
        current_status is RunStatus.RECOVERY_REQUIRED
        and command is RunCommand.RESOLVE_RECOVERY
        and recovery_next_status is None
    ):
        raise InvariantViolationError("recovery_next_status is required")

    next_status = _resolve_run_next_status(
        current_status,
        command,
        plan_requires_approval,
        recovery_next_status,
    )
    if next_status is None:
        return _run_failure(
            current_status,
            current_version,
            ResultCode.STATE_CONFLICT,
            f"{command.value} is not allowed from {current_status.value}",
        )

    return _run_success(next_status, current_version + 1)


def transition_action(
    current_status: ActionStatus,
    command: ActionCommand,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    verification_status: VerificationStatus | None = None,
    result_not_executed_confirmed: bool = False,
) -> CommandResult[ActionStatus, ActionCommand]:
    """Apply a pure Action status transition with effect and version checks."""
    if not _is_non_negative_version(current_version):
        raise InvariantViolationError("current_version must be non-negative")
    if not _is_non_negative_version(expected_version):
        raise InvariantViolationError("expected_version must be non-negative")
    if expected_version != current_version:
        return _action_failure(
            current_status,
            current_version,
            effect_type,
            ResultCode.VERSION_CONFLICT,
            "expected_version does not match current_version",
        )

    invariant_error = _validate_action_invariants(
        current_status,
        command,
        effect_type,
        verification_status,
        result_not_executed_confirmed,
    )
    if invariant_error is not None:
        raise InvariantViolationError(invariant_error)

    next_status = _resolve_action_next_status(
        current_status,
        command,
        effect_type,
        verification_status,
    )
    if next_status is None:
        return _action_failure(
            current_status,
            current_version,
            effect_type,
            ResultCode.STATE_CONFLICT,
            f"{command.value} is not allowed from {current_status.value} for {effect_type.value}",
        )

    return _action_success(next_status, current_version + 1, effect_type=effect_type)


def _is_non_negative_version(version: int) -> bool:
    return version >= 0


def _resolve_run_next_status(
    current_status: RunStatus,
    command: RunCommand,
    plan_requires_approval: bool | None,
    recovery_next_status: RunStatus | None,
) -> RunStatus | None:
    if command is RunCommand.PUBLISH_PLAN and current_status is RunStatus.PLANNING:
        if plan_requires_approval is None:
            return None
        return RunStatus.WAITING_APPROVAL if plan_requires_approval else RunStatus.EXECUTING

    if _is_cancel_candidate(current_status, command):
        return RunStatus.CANCEL_REQUESTED

    if _is_require_recovery_candidate(current_status, command):
        return RunStatus.RECOVERY_REQUIRED

    if command is RunCommand.RESOLVE_RECOVERY and current_status is RunStatus.RECOVERY_REQUIRED:
        if recovery_next_status in {
            RunStatus.VERIFYING,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return recovery_next_status
        return None

    return RUN_TRANSITIONS.get((current_status, command))


def _resolve_action_next_status(
    current_status: ActionStatus,
    command: ActionCommand,
    effect_type: EffectType,
    verification_status: VerificationStatus | None,
) -> ActionStatus | None:
    if _is_store_verification_candidate(effect_type, current_status, command):
        if verification_status is VerificationStatus.VERIFIED:
            return ActionStatus.VERIFIED
        if verification_status is VerificationStatus.MISMATCH:
            return ActionStatus.MISMATCH
        return None

    return _action_transition_table(effect_type).get((current_status, command))


def _validate_action_invariants(
    current_status: ActionStatus,
    command: ActionCommand,
    effect_type: EffectType,
    verification_status: VerificationStatus | None,
    result_not_executed_confirmed: bool,
) -> str | None:
    if (
        command is ActionCommand.RESOLVE_AS_FAILED
        and effect_type in WRITE_EFFECTS
        and current_status is ActionStatus.UNKNOWN_RESULT
        and not result_not_executed_confirmed
    ):
        return "result_not_executed_confirmed is required"

    if command is ActionCommand.STORE_VERIFICATION and (
        verification_status not in {VerificationStatus.VERIFIED, VerificationStatus.MISMATCH}
    ):
        return "verification_status must be VERIFIED or MISMATCH"

    return None


def _action_transition_table(
    effect_type: EffectType,
) -> dict[tuple[ActionStatus, ActionCommand], ActionStatus]:
    if effect_type is EffectType.READ:
        return READ_ACTION_TRANSITIONS
    return WRITE_ACTION_TRANSITIONS


def _is_publish_plan_candidate(current_status: RunStatus, command: RunCommand) -> bool:
    return current_status is RunStatus.PLANNING and command is RunCommand.PUBLISH_PLAN


def _is_cancel_candidate(current_status: RunStatus, command: RunCommand) -> bool:
    return (
        command is RunCommand.REQUEST_CANCEL
        and current_status not in RUN_TERMINAL_STATUSES
        and current_status is not RunStatus.CANCEL_REQUESTED
    )


def _is_require_recovery_candidate(current_status: RunStatus, command: RunCommand) -> bool:
    return (
        command is RunCommand.REQUIRE_RECOVERY
        and current_status not in RUN_TERMINAL_STATUSES
        and current_status is not RunStatus.RECOVERY_REQUIRED
    )


def _is_resolve_recovery_candidate(current_status: RunStatus, command: RunCommand) -> bool:
    return current_status is RunStatus.RECOVERY_REQUIRED and command is RunCommand.RESOLVE_RECOVERY


def _is_store_verification_candidate(
    effect_type: EffectType,
    current_status: ActionStatus,
    command: ActionCommand,
) -> bool:
    return (
        effect_type in WRITE_EFFECTS
        and current_status is ActionStatus.EXECUTED
        and command is ActionCommand.STORE_VERIFICATION
    )


def _run_success(
    status: RunStatus,
    version: int,
) -> CommandResult[RunStatus, RunCommand]:
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=status,
        current_version=version,
        next_allowed_commands=next_allowed_run_commands(status),
    )


def _run_failure(
    status: RunStatus,
    version: int,
    result_code: ResultCode,
    conflict_detail: str,
) -> CommandResult[RunStatus, RunCommand]:
    return CommandResult(
        applied=False,
        result_code=result_code,
        current_status=status,
        current_version=version,
        next_allowed_commands=next_allowed_run_commands(status),
        conflict_detail=conflict_detail,
    )


def _action_success(
    status: ActionStatus,
    version: int,
    *,
    effect_type: EffectType,
) -> CommandResult[ActionStatus, ActionCommand]:
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=status,
        current_version=version,
        next_allowed_commands=next_allowed_action_commands(status, effect_type=effect_type),
    )


def _action_failure(
    status: ActionStatus,
    version: int,
    effect_type: EffectType,
    result_code: ResultCode,
    conflict_detail: str,
) -> CommandResult[ActionStatus, ActionCommand]:
    return CommandResult(
        applied=False,
        result_code=result_code,
        current_status=status,
        current_version=version,
        next_allowed_commands=next_allowed_action_commands(status, effect_type=effect_type),
        conflict_detail=conflict_detail,
    )
