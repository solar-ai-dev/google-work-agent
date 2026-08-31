from google_work_agent.domain.action.guards.modify_action import guard_modify_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_modify_action.__module__.endswith("action.guards.modify_action")
