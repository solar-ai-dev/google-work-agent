from tests.unit.application.use_cases._canonical_owner import assert_owner


def test_canonical_owner() -> None:
    assert_owner(
        "google_work_agent.application.use_cases.action.fail_read_action",
        ("FailReadActionCommand", "FailReadActionResult", "FailReadActionHandler"),
        "FailReadActionHandler",
    )
