from google_work_agent.application.use_cases.run.require_reauth import RequireReauthHandler


def test_require_reauth__has_exact__application_owner() -> None:
    assert (
        RequireReauthHandler.__module__
        == "google_work_agent.application.use_cases.run.require_reauth"
    )
    assert RequireReauthHandler.__name__ == "RequireReauthHandler"
