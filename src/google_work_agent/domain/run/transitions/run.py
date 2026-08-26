"""Run transition table and compatibility transition policy."""

from google_work_agent.domain.enums import RecoveryResolution, ResultCode, RunStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.run.model import RunCommand, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_planning import transition_begin_planning
from google_work_agent.domain.run.transitions.begin_retrieval import transition_begin_retrieval
from google_work_agent.domain.run.transitions.start_analysis import transition_start_analysis
from google_work_agent.domain.version_validation import is_non_negative_version

RUN_TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.BLOCKED}
)


RECOVERY_RESOLUTION_TARGETS: dict[RecoveryResolution, RunStatus] = {
    RecoveryResolution.RECHECK: RunStatus.VERIFYING,
    RecoveryResolution.ACCEPT_PARTIAL: RunStatus.COMPLETED,
    RecoveryResolution.CREATE_CORRECTIVE_PLAN: RunStatus.PLANNING,
    RecoveryResolution.CANCEL: RunStatus.CANCELLED,
    RecoveryResolution.FAIL: RunStatus.FAILED,
}


_RECOVERY_TARGET_RESOLUTIONS = {
    target: resolution for resolution, target in RECOVERY_RESOLUTION_TARGETS.items()
}


RUN_TRANSITIONS: dict[tuple[RunStatus, RunCommand], RunStatus] = {
    (RunStatus.CREATED, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.ANALYZING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.RETRIEVING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.WAITING_CONFIRMATION, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.PLANNING, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.WAITING_APPROVAL, RunCommand.BLOCK_RUN): RunStatus.BLOCKED,
    (RunStatus.ANALYZING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.RETRIEVING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.PLANNING, RunCommand.FAIL_RUN): RunStatus.FAILED,
    (RunStatus.ANALYZING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.RETRIEVING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.PLANNING, RunCommand.COMPLETE_ANSWER_ONLY_RUN): RunStatus.COMPLETED,
    (RunStatus.VERIFYING, RunCommand.COMPLETE_WRITE_RUN): RunStatus.COMPLETED,
    (RunStatus.WAITING_APPROVAL, RunCommand.FINALIZE_ACTION_OUTCOMES): RunStatus.COMPLETED,
    (RunStatus.EXECUTING, RunCommand.FINALIZE_ACTION_OUTCOMES): RunStatus.COMPLETED,
    (RunStatus.VERIFYING, RunCommand.FINALIZE_ACTION_OUTCOMES): RunStatus.COMPLETED,
    (RunStatus.CANCEL_REQUESTED, RunCommand.FINALIZE_CANCEL): RunStatus.CANCELLED,
    (RunStatus.RETRIEVING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.WAITING_APPROVAL, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.EXECUTING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.VERIFYING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.ANALYZING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.PLANNING, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.RECOVERY_REQUIRED, RunCommand.REQUIRE_REAUTH): RunStatus.REAUTH_REQUIRED,
    (RunStatus.EXECUTING, RunCommand.BEGIN_VERIFICATION): RunStatus.VERIFYING,
    (RunStatus.WAITING_APPROVAL, RunCommand.BEGIN_VERIFICATION): RunStatus.VERIFYING,
    (RunStatus.CANCEL_REQUESTED, RunCommand.BEGIN_VERIFICATION): RunStatus.VERIFYING,
    (RunStatus.REAUTH_REQUIRED, RunCommand.BEGIN_VERIFICATION): RunStatus.VERIFYING,
}


RUN_COMMAND_ORDER = tuple(RunCommand)


def next_allowed_run_commands(current_status: RunStatus) -> tuple[RunCommand, ...]:
    if current_status in RUN_TERMINAL_STATUSES:
        return ()
    commands = [
        command
        for command in RUN_COMMAND_ORDER
        if command is not RunCommand.FINALIZE_ACTION_OUTCOMES
        and (
            (current_status, command) in RUN_TRANSITIONS
            or _is_phase_entry_candidate(current_status, command)
            or _is_publish_plan_candidate(current_status, command)
            or _is_cancel_candidate(current_status, command)
            or _is_require_recovery_candidate(current_status, command)
            or _is_resolve_recovery_candidate(current_status, command)
        )
    ]
    return tuple(dict.fromkeys(commands))


def _is_phase_entry_candidate(current_status: RunStatus, command: RunCommand) -> bool:
    try:
        if command is RunCommand.START_ANALYSIS:
            transition_start_analysis(current_status)
        elif command is RunCommand.BEGIN_RETRIEVAL:
            transition_begin_retrieval(current_status)
        elif command is RunCommand.BEGIN_PLANNING:
            transition_begin_planning(current_status)
        else:
            return False
    except RunTransitionRejected:
        return False
    return True


def transition_run(
    current_status: RunStatus,
    command: RunCommand,
    current_version: int,
    expected_version: int,
    *,
    plan_requires_approval: bool | None = None,
    recovery_resolution: RecoveryResolution | None = None,
    recovery_next_status: RunStatus | None = None,
) -> CommandResult[RunStatus, RunCommand]:
    """Apply a Run transition; recovery targets are canonical variants.

    ``recovery_next_status`` is accepted only as a compatibility input for
    existing repository callers and is immediately normalized into a
    registered ``RecoveryResolution``. It is never a transition authority.
    Unregistered target statuses fail closed.
    """
    if not is_non_negative_version(current_version):
        raise InvariantViolationError("current_version must be non-negative")
    if not is_non_negative_version(expected_version):
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
    if current_status is RunStatus.RECOVERY_REQUIRED and command is RunCommand.RESOLVE_RECOVERY:
        recovery_resolution = _normalize_recovery_resolution(
            recovery_resolution=recovery_resolution,
            recovery_next_status=recovery_next_status,
        )

    next_status = _resolve_run_next_status(
        current_status, command, plan_requires_approval, recovery_resolution
    )
    if next_status is None:
        return _run_failure(
            current_status,
            current_version,
            ResultCode.STATE_CONFLICT,
            f"{command.value} is not allowed from {current_status.value}",
        )
    return _run_success(next_status, current_version + 1)


def _normalize_recovery_resolution(
    *,
    recovery_resolution: RecoveryResolution | None,
    recovery_next_status: RunStatus | None,
) -> RecoveryResolution:
    if recovery_resolution is not None and recovery_next_status is not None:
        expected_target = RECOVERY_RESOLUTION_TARGETS.get(recovery_resolution)
        if expected_target is not recovery_next_status:
            raise InvariantViolationError("recovery resolution conflicts with compatibility target")
        return recovery_resolution
    if recovery_resolution is not None:
        return recovery_resolution
    if recovery_next_status is None:
        raise InvariantViolationError("recovery_resolution is required")
    normalized = _RECOVERY_TARGET_RESOLUTIONS.get(recovery_next_status)
    if normalized is None:
        raise InvariantViolationError("recovery target is not a registered recovery variant")
    return normalized


def _resolve_run_next_status(
    current_status: RunStatus,
    command: RunCommand,
    plan_requires_approval: bool | None,
    recovery_resolution: RecoveryResolution | None,
) -> RunStatus | None:
    if (
        current_status is RunStatus.PLANNING
        and command is RunCommand.PUBLISH_PLAN
        and plan_requires_approval is not None
    ):
        return RunStatus.WAITING_APPROVAL if plan_requires_approval else RunStatus.EXECUTING
    if _is_cancel_candidate(current_status, command):
        return RunStatus.CANCEL_REQUESTED
    if _is_require_recovery_candidate(current_status, command):
        return RunStatus.RECOVERY_REQUIRED
    if _is_resolve_recovery_candidate(current_status, command):
        return (
            None
            if recovery_resolution is None
            else RECOVERY_RESOLUTION_TARGETS[recovery_resolution]
        )
    return RUN_TRANSITIONS.get((current_status, command))


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


def _run_success(next_status: RunStatus, next_version: int) -> CommandResult[RunStatus, RunCommand]:
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=next_status,
        current_version=next_version,
        next_allowed_commands=next_allowed_run_commands(next_status),
        conflict_detail=None,
    )


def _run_failure(
    current_status: RunStatus,
    current_version: int,
    result_code: ResultCode,
    conflict_detail: str,
) -> CommandResult[RunStatus, RunCommand]:
    return CommandResult(
        applied=False,
        result_code=result_code,
        current_status=current_status,
        current_version=current_version,
        next_allowed_commands=next_allowed_run_commands(current_status),
        conflict_detail=conflict_detail,
    )
