from google_work_agent.domain.execution_attempt.guards.store_success import guard_store_success


def test_guard_authority_is_owner_local() -> None:
    assert guard_store_success.__module__.endswith("execution_attempt.guards.store_success")
