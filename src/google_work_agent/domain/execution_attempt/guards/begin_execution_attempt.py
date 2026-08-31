"""Guard for beginning a claimed execution attempt."""

from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode


def guard_begin_execution_attempt(
    current_status: ExecutionAttemptStatusV1,
    current_version: int,
    expected_version: int,
    *,
    claim_context_current: bool,
    durable_cancel_intent: bool,
) -> tuple[ResultCode, str] | None:
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status is not ExecutionAttemptStatusV1.CLAIMED:
        return ResultCode.STATE_CONFLICT, "BeginExecutionAttempt requires CLAIMED"
    if durable_cancel_intent or not claim_context_current:
        return ResultCode.STATE_CONFLICT, "claim context is no longer dispatchable"
    return None
