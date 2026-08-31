"""Guard for aborting a claimed execution before dispatch."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode


def guard_abort_claimed_execution(
    *,
    action_status: ActionStatusV1,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    begin_receipt_applied: bool,
    provider_dispatch_count: int,
) -> tuple[ResultCode, str] | None:
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return ResultCode.VERSION_CONFLICT, "expected version does not match current version"
    if (
        action_status is not ActionStatusV1.EXECUTING
        or attempt_status is not ExecutionAttemptStatusV1.CLAIMED
    ):
        return (
            ResultCode.STATE_CONFLICT,
            "AbortClaimedExecution requires Action EXECUTING and Attempt CLAIMED",
        )
    if begin_receipt_applied or provider_dispatch_count != 0:
        return ResultCode.STATE_CONFLICT, "AbortClaimedExecution is pre-dispatch only"
    return None
