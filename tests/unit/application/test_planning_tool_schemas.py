from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.planning_arguments import (
    PlanningArgumentBindingError,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
    planning_write_tool_ids,
)
from google_work_agent.domain import EffectType, build_p0_tool_registry


def test_planning_schema_catalog_matches_registered_write_tools() -> None:
    registered_write_tools = {
        entry.tool_name
        for entry in build_p0_tool_registry().list_entries()
        if entry.effect_type is not EffectType.READ
    }

    assert planning_write_tool_ids() == registered_write_tools


def test_container_bound_tools_expose_required_container_fields() -> None:
    for tool_id, field in {
        "tasks_create_task": "task_list_id",
        "tasks_update_task": "task_list_id",
        "tasks_delete_task": "task_list_id",
        "calendar_create_event": "calendar_id",
        "calendar_update_event": "calendar_id",
        "calendar_delete_event": "calendar_id",
    }.items():
        schema = planning_tool_argument_schema(tool_id)
        properties = schema["properties"]
        required = schema["required"]
        assert isinstance(properties, dict)
        assert field in properties
        assert isinstance(required, list)
        assert field in required


def test_gmail_optional_recipient_fields_cannot_be_explicit_empty_lists() -> None:
    schema = planning_tool_argument_schema("gmail_create_draft")
    properties = schema["properties"]
    assert isinstance(properties, dict)
    payload = properties["payload"]
    assert isinstance(payload, dict)
    payload_properties = payload["properties"]
    assert isinstance(payload_properties, dict)

    for field in ("to", "cc", "bcc"):
        field_schema = payload_properties[field]
        assert isinstance(field_schema, dict)
        assert field_schema["minItems"] == 1


def test_planning_schemas_never_expose_dispatch_only_metadata() -> None:
    forbidden = {
        "claim_context",
        "recovery_fingerprint",
        "approval_id",
        "execution_attempt_id",
        "execution_arguments_hash",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for tool_id in planning_write_tool_ids():
        walk(planning_tool_argument_schema(tool_id))


def test_unknown_tool_has_no_planning_schema() -> None:
    with pytest.raises(PlanningArgumentBindingError, match="no Planning business argument schema"):
        planning_tool_argument_schema("unregistered_write_tool")
