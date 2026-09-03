from google_work_agent.application.use_cases.action.reject_action import RejectActionHandler


def test_reject_action__has_exact__application_owner() -> None:
    assert (
        RejectActionHandler.__module__
        == "google_work_agent.application.use_cases.action.reject_action"
    )
    assert RejectActionHandler.__name__ == "RejectActionHandler"
