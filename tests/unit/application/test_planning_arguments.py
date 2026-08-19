from __future__ import annotations

import pytest

from google_work_agent.application.workflows.planning_arguments import (
    DefaultContainerResolver,
    PlanningArgumentBindingError,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.workflows.tool_routing import OutputToolRouteV1


def _route(*, tool_id: str, resource_type: str, effect: str = "CREATE") -> OutputToolRouteV1:
    return {
        "route_id": f"route-{tool_id}",
        "resource_type": resource_type,
        "connector_id": "google_workspace",
        "effect": effect,  # type: ignore[typeddict-item]
        "selected_tool_id": tool_id,
        "reason_codes": ["USER_REQUEST"],
    }


def _schema(*properties: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            name: ({"type": "object"} if name == "payload" else {"type": "string"})
            for name in properties
        },
        "required": list(properties),
    }


def test_task_route_binds_configured_default_as_const() -> None:
    resolver = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "task-list-default",
        default_calendar_id_provider=lambda: "calendar-default",
    )

    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="tasks_create_task", resource_type="TASK"),
        selected_tool_schema=_schema("task_list_id", "payload"),
    )

    assert bound["immutable_arguments"] == {"task_list_id": "task-list-default"}
    properties = bound["argument_schema"]["properties"]
    assert isinstance(properties, dict)
    assert properties["task_list_id"] == {
        "type": "string",
        "const": "task-list-default",
    }


def test_calendar_route_binds_configured_default_as_const() -> None:
    resolver = DefaultContainerResolver(
        default_calendar_id_provider=lambda: "primary-calendar",
    )

    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="calendar_create_event", resource_type="CALENDAR_EVENT"),
        selected_tool_schema=_schema("calendar_id", "payload"),
    )

    assert bound["immutable_arguments"] == {"calendar_id": "primary-calendar"}


def test_explicit_container_wins_over_configured_default() -> None:
    resolver = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "task-list-default",
    )

    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="tasks_create_task", resource_type="TASK"),
        selected_tool_schema=_schema("task_list_id", "payload"),
        explicit_container_id="task-list-selected",
    )

    assert bound["immutable_arguments"] == {"task_list_id": "task-list-selected"}


def test_missing_required_container_fails_closed() -> None:
    resolver = DefaultContainerResolver()

    with pytest.raises(PlanningArgumentBindingError, match="task_list_id is required"):
        resolver.bind_selected_tool_schema(
            route=_route(tool_id="tasks_create_task", resource_type="TASK"),
            selected_tool_schema=_schema("task_list_id", "payload"),
        )


def test_missing_container_field_in_selected_schema_fails_closed() -> None:
    resolver = DefaultContainerResolver(
        default_calendar_id_provider=lambda: "primary-calendar",
    )

    with pytest.raises(PlanningArgumentBindingError, match="missing required container field"):
        resolver.bind_selected_tool_schema(
            route=_route(tool_id="calendar_create_event", resource_type="CALENDAR_EVENT"),
            selected_tool_schema=_schema("payload"),
        )


def test_non_container_tool_keeps_schema_without_default_dependency() -> None:
    resolver = DefaultContainerResolver()
    selected_schema = _schema("payload")

    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="gmail_create_draft", resource_type="GMAIL_DRAFT"),
        selected_tool_schema=selected_schema,
    )

    assert bound["immutable_arguments"] == {}
    assert bound["argument_schema"] == selected_schema


def test_candidate_cannot_override_bound_container() -> None:
    resolver = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "task-list-default",
    )
    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="tasks_create_task", resource_type="TASK"),
        selected_tool_schema=_schema("task_list_id", "payload"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="override immutable task_list_id"):
        validate_tool_argument_candidate_v1(
            {
                "schema_version": 1,
                "route_id": bound["route_id"],
                "arguments": {
                    "task_list_id": "llm-invented-list",
                    "payload": {"title": "test"},
                },
                "evidence_refs": ["ev-1"],
            },
            bound_tool_schema=bound,
            allowed_evidence_refs={"ev-1"},
        )


def test_candidate_inherits_bound_container_when_omitted() -> None:
    resolver = DefaultContainerResolver(
        default_calendar_id_provider=lambda: "primary-calendar",
    )
    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="calendar_create_event", resource_type="CALENDAR_EVENT"),
        selected_tool_schema=_schema("calendar_id", "payload"),
    )

    result = validate_tool_argument_candidate_v1(
        {
            "schema_version": 1,
            "route_id": bound["route_id"],
            "arguments": {"payload": {"title": "focus"}},
            "evidence_refs": ["ev-1"],
        },
        bound_tool_schema=bound,
        allowed_evidence_refs={"ev-1"},
    )

    assert result["arguments"]["calendar_id"] == "primary-calendar"


def test_candidate_route_escape_is_rejected() -> None:
    resolver = DefaultContainerResolver()
    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="gmail_create_draft", resource_type="GMAIL_DRAFT"),
        selected_tool_schema=_schema("payload"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="escapes frozen route"):
        validate_tool_argument_candidate_v1(
            {
                "schema_version": 1,
                "route_id": "other-route",
                "arguments": {"payload": {}},
                "evidence_refs": ["ev-1"],
            },
            bound_tool_schema=bound,
            allowed_evidence_refs={"ev-1"},
        )


def test_candidate_unknown_evidence_is_rejected() -> None:
    resolver = DefaultContainerResolver()
    bound = resolver.bind_selected_tool_schema(
        route=_route(tool_id="gmail_create_draft", resource_type="GMAIL_DRAFT"),
        selected_tool_schema=_schema("payload"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="unavailable evidence"):
        validate_tool_argument_candidate_v1(
            {
                "schema_version": 1,
                "route_id": bound["route_id"],
                "arguments": {"payload": {}},
                "evidence_refs": ["ev-outside-run"],
            },
            bound_tool_schema=bound,
            allowed_evidence_refs={"ev-1"},
        )
