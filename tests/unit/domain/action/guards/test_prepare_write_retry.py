from google_work_agent.domain.action.guards.prepare_write_retry import guard_prepare_write_retry


def test_guard_authority_is_owner_local() -> None:
    assert guard_prepare_write_retry.__module__.endswith("action.guards.prepare_write_retry")
