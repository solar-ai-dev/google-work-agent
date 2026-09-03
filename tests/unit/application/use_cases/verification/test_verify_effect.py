from google_work_agent.application.use_cases.verification.verify_effect import VerifyEffectHandler


def test_verify_effect__has_exact__application_owner() -> None:
    assert (
        VerifyEffectHandler.__module__
        == "google_work_agent.application.use_cases.verification.verify_effect"
    )
    assert VerifyEffectHandler.__name__ == "VerifyEffectHandler"
