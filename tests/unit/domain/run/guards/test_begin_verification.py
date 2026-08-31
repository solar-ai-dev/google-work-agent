from google_work_agent.domain.run.guards.begin_verification import guard_begin_verification


def test_guard_authority_is_owner_local() -> None:
    assert guard_begin_verification.__module__.endswith("run.guards.begin_verification")
