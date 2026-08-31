from google_work_agent.domain.execution_attempt.guards.resolve_as_failed import (
    guard_resolve_as_failed,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_resolve_as_failed.__module__.endswith("execution_attempt.guards.resolve_as_failed")
