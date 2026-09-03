from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
)


def test_get_resource_count__has_exact__application_owner() -> None:
    assert (
        GetResourceCountHandler.__module__
        == "google_work_agent.application.use_cases.resource.get_resource_count"
    )
    assert GetResourceCountHandler.__name__ == "GetResourceCountHandler"
