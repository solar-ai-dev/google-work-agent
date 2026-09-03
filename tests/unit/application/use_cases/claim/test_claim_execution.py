from google_work_agent.application.use_cases.claim.claim_execution import ClaimExecutionHandler


def test_claim_execution__has_exact__application_owner() -> None:
    assert (
        ClaimExecutionHandler.__module__
        == "google_work_agent.application.use_cases.claim.claim_execution"
    )
    assert ClaimExecutionHandler.__name__ == "ClaimExecutionHandler"
