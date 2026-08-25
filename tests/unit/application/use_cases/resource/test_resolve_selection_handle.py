import pytest

from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
    SelectionHandleValidationError,
)


def test_resolves_only_when_all_service_session_account_and_identity_bindings_match() -> None:
    handle = _handle()
    resolver = _resolver()

    payload = resolver(
        ResolveSelectionHandleQuery(
            selection_handle=handle,
            session_digest="a" * 64,
            account_id="account-1",
            expected_connector_id="google_workspace",
            expected_resource_type="task",
            expected_resource_id="resource-1",
            expected_parent_resource_id="task-list-1",
            require_parent_match=True,
        )
    )

    assert payload.resource_id == "resource-1"
    assert payload.parent_resource_id == "task-list-1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_digest", "b" * 64),
        ("account_id", "account-2"),
        ("expected_connector_id", "other"),
        ("expected_resource_type", "calendar_event"),
        ("expected_resource_id", "resource-2"),
        ("expected_parent_resource_id", "task-list-2"),
    ],
)
def test_fails_closed_on_cross_binding_mismatch(field: str, value: str) -> None:
    values = {
        "selection_handle": _handle(),
        "session_digest": "a" * 64,
        "account_id": "account-1",
        "expected_connector_id": "google_workspace",
        "expected_resource_type": "task",
        "expected_resource_id": "resource-1",
        "expected_parent_resource_id": "task-list-1",
        "require_parent_match": True,
    }
    values[field] = value

    with pytest.raises(SelectionHandleValidationError):
        _resolver()(ResolveSelectionHandleQuery(**values))  # type: ignore[arg-type]


def test_fails_closed_on_tamper_expiry_and_service_restart() -> None:
    handle = _handle()
    query = ResolveSelectionHandleQuery(handle, "a" * 64, "account-1")

    with pytest.raises(SelectionHandleValidationError):
        _resolver()(ResolveSelectionHandleQuery(handle + "x", "a" * 64, "account-1"))
    with pytest.raises(SelectionHandleValidationError):
        _resolver(now_ms=601)(query)
    with pytest.raises(SelectionHandleValidationError):
        _resolver(service_instance_id="service-2")(query)


def _handle() -> str:
    return IssueSelectionHandle(
        signing_secret=b"s" * 32,
        service_instance_id="service-1",
        now_ms=lambda: 100,
        ttl_ms=500,
    )(
        IssueSelectionHandleCommand(
            session_digest="a" * 64,
            account_id="account-1",
            connector_id="google_workspace",
            resource_type="task",
            resource_id="resource-1",
            parent_resource_id="task-list-1",
            version_token="v1",
        )
    )


def _resolver(
    *, now_ms: int = 200, service_instance_id: str = "service-1"
) -> ResolveSelectionHandle:
    return ResolveSelectionHandle(
        signing_secret=b"s" * 32,
        service_instance_id=service_instance_id,
        now_ms=lambda: now_ms,
    )
