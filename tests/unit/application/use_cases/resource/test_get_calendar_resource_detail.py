"""Calendar resource-detail contract tests."""

from importlib import import_module

from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.application.use_cases.resource.get_calendar_resource_detail import (
    GetCalendarResourceDetailHandler,
    GetCalendarResourceDetailQuery,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module(
            "google_work_agent.application.use_cases.resource.get_calendar_resource_detail"
        )
        is not None
    )


class _CalendarRead:
    def execute_read(
        self,
        _binding: ValidatedConnectorToolBindingV1,
        _tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        return ConnectorReadResultV1(
            1,
            "calendar_get_event",
            "read-1",
            {
                "item": {
                    "resource_id": "event-1",
                    "parent_id": "primary",
                    "payload": {
                        "title": "Review",
                        "start": "2026-09-01T09:00:00+09:00",
                        "end": "2026-09-01T10:00:00+09:00",
                        "timezone": "Asia/Seoul",
                        "attendees": ["reviewer@example.com"],
                        "location": "Room 1",
                        "description": "Weekly review",
                    },
                }
            },
            None,
            None,
        )


def test_calendar_detail_projects_closed_contract() -> None:
    signing_secret = b"s" * 32
    handle = IssueSelectionHandle(
        signing_secret=signing_secret,
        service_instance_id="svc-1",
        now_ms=lambda: 1_000,
        ttl_ms=60_000,
    )(
        IssueSelectionHandleCommand(
            session_digest="a" * 64,
            account_id="account-1",
            connector_id="google_workspace",
            resource_type="calendar_event",
            resource_id="event-1",
            parent_resource_id="primary",
            version_token="1",
        )
    )
    result = GetCalendarResourceDetailHandler(
        resolve_handle=ResolveSelectionHandle(
            signing_secret=signing_secret,
            service_instance_id="svc-1",
            now_ms=lambda: 1_000,
        ),
        connector_read=_CalendarRead(),
        registry=load_signed_tool_registry(),
    )(
        GetCalendarResourceDetailQuery(
            resource_id="event-1",
            selection_handle=handle,
            session_digest="a" * 64,
            account_id="account-1",
        )
    )

    assert result.calendar_id == "primary"
    assert result.timezone == "Asia/Seoul"
    assert result.attendees == ("reviewer@example.com",)
