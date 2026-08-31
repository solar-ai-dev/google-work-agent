from google_work_agent.domain.action.guards.finalize_read_action import guard_finalize_read_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_finalize_read_action.__module__.endswith("action.guards.finalize_read_action")
