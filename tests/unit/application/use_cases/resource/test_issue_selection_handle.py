from dataclasses import replace

import pytest

from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
    IssueSelectionHandleCommand,
)


def test_issues_opaque_authenticated_handle_without_exposing_plain_identity() -> None:
    issuer = IssueSelectionHandle(
        signing_secret=b"s" * 32,
        service_instance_id="service-1",
        now_ms=lambda: 100,
        ttl_ms=500,
    )

    handle = issuer(_command())

    assert handle.startswith("v1.")
    assert "resource-1" not in handle
    assert "account-1" not in handle


def test_rejects_non_digest_session_binding() -> None:
    issuer = IssueSelectionHandle(
        signing_secret=b"s" * 32,
        service_instance_id="service-1",
        now_ms=lambda: 100,
        ttl_ms=500,
    )

    with pytest.raises(ValueError, match="session_digest"):
        issuer(replace(_command(), session_digest="raw"))


def _command() -> IssueSelectionHandleCommand:
    return IssueSelectionHandleCommand(
        session_digest="a" * 64,
        account_id="account-1",
        connector_id="google_workspace",
        resource_type="task",
        resource_id="resource-1",
        parent_resource_id="task-list-1",
        version_token="v1",
    )
