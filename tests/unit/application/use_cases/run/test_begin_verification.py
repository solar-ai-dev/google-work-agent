from google_work_agent.application.use_cases.run.begin_verification import BeginVerificationHandler


def test_begin_verification__has_exact__application_owner() -> None:
    assert (
        BeginVerificationHandler.__module__
        == "google_work_agent.application.use_cases.run.begin_verification"
    )
    assert BeginVerificationHandler.__name__ == "BeginVerificationHandler"
