from google_work_agent.domain.execution_attempt.guards.abort_claimed_execution import (
    guard_abort_claimed_execution,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_abort_claimed_execution.__module__.endswith(
        "execution_attempt.guards.abort_claimed_execution"
    )
