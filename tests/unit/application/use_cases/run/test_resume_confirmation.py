from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
)


def test_resume_confirmation__has_exact__application_owner() -> None:
    assert (
        ResumeConfirmationHandler.__module__
        == "google_work_agent.application.use_cases.run.resume_confirmation"
    )
    assert ResumeConfirmationHandler.__name__ == "ResumeConfirmationHandler"
