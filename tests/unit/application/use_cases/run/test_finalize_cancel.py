from google_work_agent.application.use_cases.run.finalize_cancel import FinalizeCancelHandler


def test_finalize_cancel__has_exact__application_owner() -> None:
    assert (
        FinalizeCancelHandler.__module__
        == "google_work_agent.application.use_cases.run.finalize_cancel"
    )
    assert FinalizeCancelHandler.__name__ == "FinalizeCancelHandler"
