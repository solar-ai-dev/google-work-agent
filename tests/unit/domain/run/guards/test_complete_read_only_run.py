from google_work_agent.domain.run.guards.complete_read_only_run import (
    guard_complete_read_only_run,
)


def test_guard_authority_is_owner_local() -> None:
    assert guard_complete_read_only_run.__module__.endswith("run.guards.complete_read_only_run")
