from google_work_agent.domain.verification.guards.store_verification import (
    guard_store_verification,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_store_verification.__module__.endswith("verification.guards.store_verification")
