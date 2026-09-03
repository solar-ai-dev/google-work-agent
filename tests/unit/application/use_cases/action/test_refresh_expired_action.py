from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionHandler,
)


def test_refresh_expired_action__has_exact__application_owner() -> None:
    assert (
        RefreshExpiredActionHandler.__module__
        == "google_work_agent.application.use_cases.action.refresh_expired_action"
    )
    assert RefreshExpiredActionHandler.__name__ == "RefreshExpiredActionHandler"
