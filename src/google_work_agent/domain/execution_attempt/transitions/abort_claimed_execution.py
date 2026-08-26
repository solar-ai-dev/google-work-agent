"""Settle a claimed Attempt before any provider dispatch."""

from dataclasses import dataclass

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.results import ResultCode


@dataclass(frozen=True, slots=True)
class AbortClaimedExecutionDecision:
    applied: bool
    result_code: ResultCode
    action_status: ActionStatus
    action_version: int
    attempt_status: ExecutionAttemptStatus
    attempt_version: int
    conflict_detail: str | None = None


def transition_abort_claimed_execution(
    *,
    action_status: ActionStatus,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatus,
    attempt_version: int,
    expected_attempt_version: int,
    durable_cancel_intent: bool,
    begin_receipt_applied: bool,
    provider_dispatch_count: int,
) -> AbortClaimedExecutionDecision:
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return AbortClaimedExecutionDecision(
            False,
            ResultCode.VERSION_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "expected version does not match current version",
        )
    if (
        action_status is not ActionStatus.EXECUTING
        or attempt_status is not ExecutionAttemptStatus.CLAIMED
    ):
        return AbortClaimedExecutionDecision(
            False,
            ResultCode.STATE_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "AbortClaimedExecution requires Action EXECUTING and Attempt CLAIMED",
        )
    if begin_receipt_applied or provider_dispatch_count != 0:
        return AbortClaimedExecutionDecision(
            False,
            ResultCode.STATE_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "AbortClaimedExecution is pre-dispatch only",
        )
    return AbortClaimedExecutionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatus.CANCELLED if durable_cancel_intent else ActionStatus.FAILED,
        action_version + 1,
        ExecutionAttemptStatus.FAILED,
        attempt_version + 1,
    )
