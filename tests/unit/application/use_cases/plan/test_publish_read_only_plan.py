from tests.unit.application.use_cases._canonical_owner import assert_owner


def test_canonical_owner() -> None:
    assert_owner(
        "google_work_agent.application.use_cases.plan.publish_read_only_plan",
        ("PublishReadOnlyPlanCommand", "PublishReadOnlyPlanResult", "PublishReadOnlyPlanHandler"),
        "PublishReadOnlyPlanHandler",
    )
