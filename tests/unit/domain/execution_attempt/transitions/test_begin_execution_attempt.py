from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.begin_execution_attempt import (
    transition_begin_execution_attempt,
)


def test_begin_execution__attempt_is_the__only_dispatch_authority() -> None:
    allowed = transition_begin_execution_attempt(
        ExecutionAttemptStatusV1.CLAIMED,
        0,
        0,
        claim_context_current=True,
        durable_cancel_intent=False,
    )
    cancelled = transition_begin_execution_attempt(
        ExecutionAttemptStatusV1.CLAIMED,
        0,
        0,
        claim_context_current=True,
        durable_cancel_intent=True,
    )
    assert allowed.applied and allowed.current_status is ExecutionAttemptStatusV1.EXECUTING
    assert not cancelled.applied
