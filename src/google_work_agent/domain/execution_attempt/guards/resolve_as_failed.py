"""Guard for resolving a confirmed non-executed result as failed."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import InvariantViolationError, ResultCode


def guard_resolve_as_failed(
    action_status: ActionStatusV1,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    result_not_executed_confirmed: bool,
) -> tuple[ResultCode, str] | None:
    if not result_not_executed_confirmed:
        raise InvariantViolationError("ResolveAsFailed requires confirmed non-execution")
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return ResultCode.VERSION_CONFLICT, "expected version does not match current version"
    if (
        action_status is not ActionStatusV1.UNKNOWN_RESULT
        or attempt_status is not ExecutionAttemptStatusV1.UNKNOWN_RESULT
    ):
        return (
            ResultCode.STATE_CONFLICT,
            "ResolveAsFailed requires Action and Attempt UNKNOWN_RESULT",
        )
    return None
