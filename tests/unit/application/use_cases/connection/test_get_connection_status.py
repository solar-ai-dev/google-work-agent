from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
)


def test_get_connection_status__has_exact__application_owner() -> None:
    assert (
        GetConnectionStatusHandler.__module__
        == "google_work_agent.application.use_cases.connection.get_connection_status"
    )
    assert GetConnectionStatusHandler.__name__ == "GetConnectionStatusHandler"
