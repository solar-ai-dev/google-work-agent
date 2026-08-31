from google_work_agent.domain.action.guards.fail_read_action import guard_fail_read_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_fail_read_action.__module__.endswith("action.guards.fail_read_action")
