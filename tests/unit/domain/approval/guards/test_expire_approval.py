from google_work_agent.domain.approval.guards.expire_approval import guard_expire_approval


def test_guard_authority_is_owner_local() -> None:
    assert guard_expire_approval.__module__.endswith("approval.guards.expire_approval")
