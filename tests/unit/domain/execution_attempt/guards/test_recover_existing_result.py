from google_work_agent.domain.execution_attempt.guards.recover_existing_result import (
    guard_recover_existing_result,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_recover_existing_result.__module__.endswith(
        "execution_attempt.guards.recover_existing_result"
    )
