"""Action transition table and compatibility transition policy."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode, VerificationStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.version_validation import is_non_negative_version

ACTION_TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.REJECTED,
        ActionStatus.VERIFIED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.MISMATCH,
        ActionStatus.CANCELLED,
    }
)


WRITE_EFFECTS = frozenset(
    {EffectType.CREATE, EffectType.UPDATE, EffectType.SEND, EffectType.DELETE}
)


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
    (ActionStatus.PROPOSED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.MODIFIED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.APPROVED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.EXPIRED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
}


WRITE_ACTION_TRANSITIONS: dict[tuple[ActionStatus, ActionCommand], ActionStatus] = {
    (ActionStatus.PROPOSED, ActionCommand.APPROVE_ACTION): ActionStatus.APPROVED,
    (ActionStatus.MODIFIED, ActionCommand.APPROVE_ACTION): ActionStatus.APPROVED,
    (ActionStatus.PROPOSED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.APPROVED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.MODIFIED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.EXPIRED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.FAILED, ActionCommand.MODIFY_ACTION): ActionStatus.MODIFIED,
    (ActionStatus.PROPOSED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.MODIFIED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.APPROVED, ActionCommand.REJECT_ACTION): ActionStatus.REJECTED,
    (ActionStatus.APPROVED, ActionCommand.EXPIRE_APPROVAL): ActionStatus.EXPIRED,
    (ActionStatus.APPROVED, ActionCommand.CLAIM_EXECUTION): ActionStatus.EXECUTING,
    (ActionStatus.EXECUTING, ActionCommand.STORE_SUCCESS): ActionStatus.EXECUTED,
    (ActionStatus.EXECUTING, ActionCommand.MARK_FAILED): ActionStatus.FAILED,
    (ActionStatus.EXECUTING, ActionCommand.MARK_UNKNOWN_RESULT): ActionStatus.UNKNOWN_RESULT,
    (ActionStatus.UNKNOWN_RESULT, ActionCommand.RECOVER_EXISTING_RESULT): ActionStatus.EXECUTED,
    (ActionStatus.UNKNOWN_RESULT, ActionCommand.RESOLVE_AS_FAILED): ActionStatus.FAILED,
    (ActionStatus.FAILED, ActionCommand.PREPARE_WRITE_RETRY): ActionStatus.MODIFIED,
    (ActionStatus.PROPOSED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.MODIFIED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.APPROVED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
    (ActionStatus.EXPIRED, ActionCommand.CANCEL_PENDING_ACTION): ActionStatus.CANCELLED,
}


def next_allowed_action_commands(
    current_status: ActionStatus, *, effect_type: EffectType
) -> tuple[ActionCommand, ...]:
    if current_status in ACTION_TERMINAL_STATUSES:
        return ()
    transition_table = _action_transition_table(effect_type)
    commands = [
        command
        for command in ACTION_COMMAND_ORDER
        if command is not ActionCommand.CANCEL_PENDING_ACTION
        and (
            (current_status, command) in transition_table
            or _is_store_verification_candidate(effect_type, current_status, command)
        )
    ]
    return tuple(dict.fromkeys(commands))


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
    if not is_non_negative_version(current_version):
        raise InvariantViolationError("current_version must be non-negative")
    if not is_non_negative_version(expected_version):
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
        current_status, command, effect_type, verification_status
    )
    if next_status is None:
        return _action_failure(
            current_status,
            current_version,
            effect_type,
            ResultCode.STATE_CONFLICT,
            f"{command.value} is not allowed from {current_status.value}",
        )
    return _action_success(next_status, current_version + 1)


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


def _action_transition_table(
    effect_type: EffectType,
) -> dict[tuple[ActionStatus, ActionCommand], ActionStatus]:
    return READ_ACTION_TRANSITIONS if effect_type is EffectType.READ else WRITE_ACTION_TRANSITIONS


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


def _validate_action_invariants(
    current_status: ActionStatus,
    command: ActionCommand,
    effect_type: EffectType,
    verification_status: VerificationStatus | None,
    result_not_executed_confirmed: bool,
) -> str | None:
    if command is ActionCommand.STORE_VERIFICATION:
        if effect_type is EffectType.READ:
            return "READ actions do not create write verification rows"
        if verification_status not in {VerificationStatus.VERIFIED, VerificationStatus.MISMATCH}:
            return "verification_status must be VERIFIED or MISMATCH"
    if (
        current_status is ActionStatus.UNKNOWN_RESULT
        and command is ActionCommand.RESOLVE_AS_FAILED
        and not result_not_executed_confirmed
    ):
        return "UNKNOWN_RESULT can resolve to FAILED only when non-execution is confirmed"
    return None


def _action_success(
    next_status: ActionStatus, next_version: int
) -> CommandResult[ActionStatus, ActionCommand]:
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=next_status,
        current_version=next_version,
        next_allowed_commands=next_allowed_action_commands(
            next_status,
            effect_type=(
                EffectType.READ
                if next_status in {ActionStatus.EXECUTING, ActionStatus.EXECUTED}
                else EffectType.CREATE
            ),
        ),
        conflict_detail=None,
    )


def _action_failure(
    current_status: ActionStatus,
    current_version: int,
    effect_type: EffectType,
    result_code: ResultCode,
    conflict_detail: str,
) -> CommandResult[ActionStatus, ActionCommand]:
    return CommandResult(
        applied=False,
        result_code=result_code,
        current_status=current_status,
        current_version=current_version,
        next_allowed_commands=next_allowed_action_commands(current_status, effect_type=effect_type),
        conflict_detail=conflict_detail,
    )
