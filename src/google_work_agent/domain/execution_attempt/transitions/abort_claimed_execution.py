"""Settle a claimed Attempt before any provider dispatch."""

from dataclasses import dataclass

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.guards.abort_claimed_execution import (
    guard_abort_claimed_execution,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode


@dataclass(frozen=True, slots=True)
class AbortClaimedExecutionDecision:
    applied: bool
    result_code: ResultCode
    action_status: ActionStatusV1
    action_version: int
    attempt_status: ExecutionAttemptStatusV1
    attempt_version: int
    conflict_detail: str | None = None


def transition_abort_claimed_execution(
    *,
    action_status: ActionStatusV1,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    durable_cancel_intent: bool,
    begin_receipt_applied: bool,
    provider_dispatch_count: int,
) -> AbortClaimedExecutionDecision:
    conflict = guard_abort_claimed_execution(
        action_status=action_status,
        action_version=action_version,
        expected_action_version=expected_action_version,
        attempt_status=attempt_status,
        attempt_version=attempt_version,
        expected_attempt_version=expected_attempt_version,
        begin_receipt_applied=begin_receipt_applied,
        provider_dispatch_count=provider_dispatch_count,
    )
    if conflict is not None:
        return AbortClaimedExecutionDecision(
            False,
            conflict[0],
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            conflict[1],
        )
    return AbortClaimedExecutionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatusV1.CANCELLED if durable_cancel_intent else ActionStatusV1.FAILED,
        action_version + 1,
        ExecutionAttemptStatusV1.FAILED,
        attempt_version + 1,
    )
