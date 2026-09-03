from google_work_agent.application.use_cases.run.begin_retrieval import BeginRetrievalHandler


def test_begin_retrieval__has_exact__application_owner() -> None:
    assert (
        BeginRetrievalHandler.__module__
        == "google_work_agent.application.use_cases.run.begin_retrieval"
    )
    assert BeginRetrievalHandler.__name__ == "BeginRetrievalHandler"
