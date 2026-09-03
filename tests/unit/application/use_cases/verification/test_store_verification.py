from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationHandler,
)


def test_store_verification__has_exact__application_owner() -> None:
    assert (
        StoreVerificationHandler.__module__
        == "google_work_agent.application.use_cases.verification.store_verification"
    )
    assert StoreVerificationHandler.__name__ == "StoreVerificationHandler"
