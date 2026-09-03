from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryHandler,
)


def test_prepare_write_retry__has_exact__application_owner() -> None:
    assert (
        PrepareWriteRetryHandler.__module__
        == "google_work_agent.application.use_cases.action.prepare_write_retry"
    )
    assert PrepareWriteRetryHandler.__name__ == "PrepareWriteRetryHandler"
