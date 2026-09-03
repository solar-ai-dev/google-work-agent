from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)


def test_recover_existing_result__has_exact__application_owner() -> None:
    assert (
        RecoverExistingResultHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.recover_existing_result"
    )
    assert RecoverExistingResultHandler.__name__ == "RecoverExistingResultHandler"
