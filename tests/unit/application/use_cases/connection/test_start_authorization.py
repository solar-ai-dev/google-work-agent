from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationHandler,
)


def test_start_authorization__has_exact__application_owner() -> None:
    assert (
        StartAuthorizationHandler.__module__
        == "google_work_agent.application.use_cases.connection.start_authorization"
    )
    assert StartAuthorizationHandler.__name__ == "StartAuthorizationHandler"
