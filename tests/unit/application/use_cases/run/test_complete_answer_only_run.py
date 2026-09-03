from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunHandler,
)


def test_complete_answer_only_run__has_exact__application_owner() -> None:
    assert (
        CompleteAnswerOnlyRunHandler.__module__
        == "google_work_agent.application.use_cases.run.complete_answer_only_run"
    )
    assert CompleteAnswerOnlyRunHandler.__name__ == "CompleteAnswerOnlyRunHandler"
