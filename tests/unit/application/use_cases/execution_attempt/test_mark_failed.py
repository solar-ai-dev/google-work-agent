from google_work_agent.application.use_cases.execution_attempt.mark_failed import MarkFailedHandler


def test_mark_failed__has_exact__application_owner() -> None:
    assert (
        MarkFailedHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.mark_failed"
    )
    assert MarkFailedHandler.__name__ == "MarkFailedHandler"
