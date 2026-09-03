from google_work_agent.application.use_cases.run.request_confirmation import (
    RequestConfirmationHandler,
)


def test_request_confirmation__has_exact__application_owner() -> None:
    assert (
        RequestConfirmationHandler.__module__
        == "google_work_agent.application.use_cases.run.request_confirmation"
    )
    assert RequestConfirmationHandler.__name__ == "RequestConfirmationHandler"
