"""Authorize connector dispatch by advancing the durable Attempt."""

from google_work_agent.domain.execution_attempt.guards.begin_execution_attempt import (
    guard_begin_execution_attempt,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptCommand,
    ExecutionAttemptStatusV1,
)
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_begin_execution_attempt(
    current_status: ExecutionAttemptStatusV1,
    current_version: int,
    expected_version: int,
    *,
    claim_context_current: bool,
    durable_cancel_intent: bool,
) -> CommandResult[ExecutionAttemptStatusV1, ExecutionAttemptCommand]:
    conflict = guard_begin_execution_attempt(
        current_status,
        current_version,
        expected_version,
        claim_context_current=claim_context_current,
        durable_cancel_intent=durable_cancel_intent,
    )
    if conflict is not None:
        return CommandResult(
            False,
            conflict[0],
            current_status,
            current_version,
            (),
            conflict[1],
        )
    return CommandResult(
        True,
        ResultCode.TRANSITION_APPLIED,
        ExecutionAttemptStatusV1.EXECUTING,
        current_version + 1,
        (),
    )
