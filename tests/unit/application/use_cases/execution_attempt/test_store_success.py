from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessHandler,
)


def test_store_success__has_exact__application_owner() -> None:
    assert (
        StoreSuccessHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.store_success"
    )
    assert StoreSuccessHandler.__name__ == "StoreSuccessHandler"
