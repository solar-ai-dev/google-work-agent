from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.execution_attempt.transitions.abort_claimed_execution import (
    transition_abort_claimed_execution,
)


def test_abort_claimed_execution_is_pre_dispatch_only() -> None:
    aborted = transition_abort_claimed_execution(
        action_status=ActionStatus.EXECUTING,
        action_version=1,
        expected_action_version=1,
        attempt_status=ExecutionAttemptStatus.CLAIMED,
        attempt_version=0,
        expected_attempt_version=0,
        durable_cancel_intent=False,
        begin_receipt_applied=False,
        provider_dispatch_count=0,
    )
    dispatched = transition_abort_claimed_execution(
        action_status=ActionStatus.EXECUTING,
        action_version=1,
        expected_action_version=1,
        attempt_status=ExecutionAttemptStatus.CLAIMED,
        attempt_version=0,
        expected_attempt_version=0,
        durable_cancel_intent=False,
        begin_receipt_applied=True,
        provider_dispatch_count=0,
    )
    assert (
        aborted.applied
        and aborted.action_status is ActionStatus.FAILED
        and aborted.attempt_status is ExecutionAttemptStatus.FAILED
    )
    assert not dispatched.applied
