from google_work_agent.domain.action.guards.complete_read_action import guard_complete_read_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_complete_read_action.__module__.endswith("action.guards.complete_read_action")
