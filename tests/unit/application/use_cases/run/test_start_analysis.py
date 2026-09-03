from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisHandler


def test_start_analysis__has_exact__application_owner() -> None:
    assert (
        StartAnalysisHandler.__module__
        == "google_work_agent.application.use_cases.run.start_analysis"
    )
    assert StartAnalysisHandler.__name__ == "StartAnalysisHandler"
