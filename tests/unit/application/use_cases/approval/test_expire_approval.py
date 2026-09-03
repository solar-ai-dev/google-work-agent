from google_work_agent.application.use_cases.approval.expire_approval import ExpireApprovalHandler


def test_expire_approval__has_exact__application_owner() -> None:
    assert (
        ExpireApprovalHandler.__module__
        == "google_work_agent.application.use_cases.approval.expire_approval"
    )
    assert ExpireApprovalHandler.__name__ == "ExpireApprovalHandler"
