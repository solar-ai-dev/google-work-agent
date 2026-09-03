from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
)


def test_resolve_as_failed__has_exact__application_owner() -> None:
    assert (
        ResolveAsFailedHandler.__module__
        == "google_work_agent.application.use_cases.execution_attempt.resolve_as_failed"
    )
    assert ResolveAsFailedHandler.__name__ == "ResolveAsFailedHandler"
