from google_work_agent.domain.execution_attempt.guards.begin_execution_attempt import (
    guard_begin_execution_attempt,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_begin_execution_attempt.__module__.endswith(
        "execution_attempt.guards.begin_execution_attempt"
    )
