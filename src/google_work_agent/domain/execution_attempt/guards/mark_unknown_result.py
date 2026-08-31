"""Guard for recording an uncertain write result."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode


def guard_mark_unknown_result(
    action_status: ActionStatusV1,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
) -> tuple[ResultCode, str] | None:
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return ResultCode.VERSION_CONFLICT, "expected version does not match current version"
    if (
        action_status is not ActionStatusV1.EXECUTING
        or attempt_status is not ExecutionAttemptStatusV1.EXECUTING
    ):
        return (
            ResultCode.STATE_CONFLICT,
            "MarkUnknownResult requires Action EXECUTING and Attempt EXECUTING",
        )
    return None
