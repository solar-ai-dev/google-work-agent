from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptHandler,
)


def test_begin_execution_attempt__has_exact__application_owner() -> None:
    assert (
        BeginExecutionAttemptHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt"
    )
    assert BeginExecutionAttemptHandler.__name__ == "BeginExecutionAttemptHandler"
