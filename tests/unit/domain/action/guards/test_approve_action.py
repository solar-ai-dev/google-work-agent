from google_work_agent.domain.action.guards.approve_action import guard_approve_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_approve_action.__module__.endswith("action.guards.approve_action")
