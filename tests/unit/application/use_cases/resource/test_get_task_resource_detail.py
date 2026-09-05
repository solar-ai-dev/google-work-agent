"""Task resource-detail contract tests."""

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.resource.get_task_resource_detail import (
    GetTaskResourceDetailHandler,
    GetTaskResourceDetailQuery,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _TaskRead:
    arguments: dict[str, JsonValue] | None = None

    def __init__(self, notes: str) -> None:
        self.notes = notes

    def execute_read(
        self,
        _binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        self.arguments = tool_arguments
        return ConnectorReadResultV1(
            1,
            "tasks_get_task",
            "read-1",
            {
                "item": {
                    "resource_id": "task-1",
                    "parent_id": "list-1",
                    "payload": {
                        "title": "Follow up",
                        "status": "needsAction",
                        "due": "2026-09-01T00:00:00Z",
                        "notes": self.notes,
                    },
                }
            },
            None,
            None,
        )


@pytest.mark.parametrize("notes", [
    "Call customer", "Call customer\n\n\u200bgwa-recovery-fingerprint:abc123",
    "Call customer\u200bgwa-recovery-fingerprint:abc123",
])
def test_task_detail_projects__closed_contract_and__uses_canonical_connector_arguments(
    notes: str,
) -> None:
    signing_secret = b"s" * 32
    issuer = IssueSelectionHandle(
        signing_secret=signing_secret,
        service_instance_id="svc-1",
        now_ms=lambda: 1_000,
        ttl_ms=60_000,
    )
    handle = issuer(
        IssueSelectionHandleCommand(
            session_digest="a" * 64,
            account_id="account-1",
            connector_id="google_workspace",
            resource_type="task",
            resource_id="task-1",
            parent_resource_id="list-1",
            version_token="1",
        )
    )
    read = _TaskRead(notes)
    result = GetTaskResourceDetailHandler(
        resolve_handle=ResolveSelectionHandle(
            signing_secret=signing_secret,
            service_instance_id="svc-1",
            now_ms=lambda: 1_000,
        ),
        connector_read=read,
        registry=load_signed_tool_registry(),
    )(
        GetTaskResourceDetailQuery(
            resource_id="task-1",
            selection_handle=handle,
            session_digest="a" * 64,
            account_id="account-1",
        )
    )

    assert result.task_status == "incomplete"
    assert result.tasklist_id == "list-1"
    assert result.notes == "Call customer"
    assert result.scheduled_date == "2026-09-01"
    assert read.notes == notes
    assert read.arguments == {"task_list_id": "list-1", "task_id": "task-1"}
