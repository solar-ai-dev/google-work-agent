from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GetResourceDetailHandler,
)


def test_get_resource_detail__has_exact__application_owner() -> None:
    assert (
        GetResourceDetailHandler.__module__
        == "google_work_agent.application.use_cases.resource.get_resource_detail"
    )
    assert GetResourceDetailHandler.__name__ == "GetResourceDetailHandler"
