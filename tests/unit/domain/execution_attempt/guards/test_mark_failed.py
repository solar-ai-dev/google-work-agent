from google_work_agent.domain.execution_attempt.guards.mark_failed import guard_mark_failed


def test_guard_authority_is_owner_local() -> None:
    assert guard_mark_failed.__module__.endswith("execution_attempt.guards.mark_failed")
