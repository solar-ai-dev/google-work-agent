from google_work_agent.application.use_cases.action.cancel_pending_action import (
    CancelPendingActionHandler,
)


def test_cancel_pending_action__has_exact__application_owner() -> None:
    assert (
        CancelPendingActionHandler.__module__
        == "google_work_agent.application.use_cases.action.cancel_pending_action"
    )
    assert CancelPendingActionHandler.__name__ == "CancelPendingActionHandler"
