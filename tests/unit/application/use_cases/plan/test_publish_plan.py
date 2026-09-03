from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler


def test_publish_plan__has_exact__application_owner() -> None:
    assert (
        PublishPlanHandler.__module__ == "google_work_agent.application.use_cases.plan.publish_plan"
    )
    assert PublishPlanHandler.__name__ == "PublishPlanHandler"
