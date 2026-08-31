from google_work_agent.domain.action.guards.claim_read_action import guard_claim_read_action


def test_guard_authority_is_owner_local() -> None:
    assert guard_claim_read_action.__module__.endswith("action.guards.claim_read_action")
