from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionHandler,
)


def test_abort_claimed_execution__has_exact__application_owner() -> None:
    assert (
        AbortClaimedExecutionHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution"
    )
    assert AbortClaimedExecutionHandler.__name__ == "AbortClaimedExecutionHandler"
