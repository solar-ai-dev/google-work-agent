from google_work_agent.domain.execution_attempt.guards.mark_unknown_result import (
    guard_mark_unknown_result,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_mark_unknown_result.__module__.endswith(
        "execution_attempt.guards.mark_unknown_result"
    )
