from google_work_agent.domain.plan.guards.publish_plan import guard_publish_plan


def test_guard_authority_is_owner_local() -> None:
    assert guard_publish_plan.__module__.endswith("plan.guards.publish_plan")
