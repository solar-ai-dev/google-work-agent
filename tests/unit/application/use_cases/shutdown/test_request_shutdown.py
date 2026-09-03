from google_work_agent.application.use_cases.shutdown.request_shutdown import RequestShutdownHandler


def test_request_shutdown__has_exact__application_owner() -> None:
    assert (
        RequestShutdownHandler.__module__
        == "google_work_agent.application.use_cases.shutdown.request_shutdown"
    )
    assert RequestShutdownHandler.__name__ == "RequestShutdownHandler"
