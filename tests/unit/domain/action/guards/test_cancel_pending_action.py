from google_work_agent.domain.action.guards.cancel_pending_action import (
    guard_cancel_pending_action,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_cancel_pending_action.__module__.endswith("action.guards.cancel_pending_action")
