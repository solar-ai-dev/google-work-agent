from google_work_agent.domain.action.guards.refresh_expired_action import (
    guard_refresh_expired_action,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_refresh_expired_action.__module__.endswith("action.guards.refresh_expired_action")
