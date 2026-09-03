from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
)


def test_get_runtime_status__has_exact__application_owner() -> None:
    assert (
        GetRuntimeStatusHandler.__module__
        == "google_work_agent.application.use_cases.runtime_status.get_runtime_status"
    )
    assert GetRuntimeStatusHandler.__name__ == "GetRuntimeStatusHandler"
