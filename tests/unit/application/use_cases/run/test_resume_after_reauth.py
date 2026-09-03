from google_work_agent.application.use_cases.run.resume_after_reauth import ResumeAfterReauthHandler


def test_resume_after_reauth__has_exact__application_owner() -> None:
    assert (
        ResumeAfterReauthHandler.__module__
        == "google_work_agent.application.use_cases.run.resume_after_reauth"
    )
    assert ResumeAfterReauthHandler.__name__ == "ResumeAfterReauthHandler"
