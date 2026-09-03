from google_work_agent.application.use_cases.run.complete_write_run import CompleteWriteRunHandler


def test_complete_write_run__has_exact__application_owner() -> None:
    assert (
        CompleteWriteRunHandler.__module__
        == "google_work_agent.application.use_cases.run.complete_write_run"
    )
    assert CompleteWriteRunHandler.__name__ == "CompleteWriteRunHandler"
