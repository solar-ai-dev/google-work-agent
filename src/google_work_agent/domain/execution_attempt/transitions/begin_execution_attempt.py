"""Authorize connector dispatch by advancing the durable Attempt."""

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
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status is not ExecutionAttemptStatusV1.CLAIMED:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "BeginExecutionAttempt requires CLAIMED",
        )
    if durable_cancel_intent or not claim_context_current:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "claim context is no longer dispatchable",
        )
    return CommandResult(
        True,
        ResultCode.TRANSITION_APPLIED,
        ExecutionAttemptStatusV1.EXECUTING,
        current_version + 1,
        (),
    )
