from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultHandler,
)


def test_mark_unknown_result__has_exact__application_owner() -> None:
    assert (
        MarkUnknownResultHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.mark_unknown_result"
    )
    assert MarkUnknownResultHandler.__name__ == "MarkUnknownResultHandler"
