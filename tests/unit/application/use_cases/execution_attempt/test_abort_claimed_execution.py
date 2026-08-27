from tests.unit.application.use_cases._canonical_owner import assert_owner


def test_canonical_owner() -> None:
    assert_owner(
        "google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution",
        (
            "AbortClaimedExecutionCommandV1",
            "AbortClaimedExecutionResultV1",
            "AbortClaimedExecutionHandler",
        ),
        "AbortClaimedExecutionHandler",
    )
