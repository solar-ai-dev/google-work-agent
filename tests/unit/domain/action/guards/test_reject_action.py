from google_work_agent.domain.action.guards.reject_action import guard_reject_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_reject_action.__module__.endswith("action.guards.reject_action")
