from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)


def test_lookup_unknown_result__has_exact__application_owner() -> None:
    assert (
        LookupUnknownResultHandler.__module__
        == "google_work_agent.application.use_cases.recovery.lookup_unknown_result"
    )
    assert LookupUnknownResultHandler.__name__ == "LookupUnknownResultHandler"
