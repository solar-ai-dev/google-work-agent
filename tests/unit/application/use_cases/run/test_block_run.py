from google_work_agent.application.use_cases.run.block_run import BlockRunHandler


def test_block_run__has_exact__application_owner() -> None:
    assert BlockRunHandler.__module__ == "google_work_agent.application.use_cases.run.block_run"
    assert BlockRunHandler.__name__ == "BlockRunHandler"
