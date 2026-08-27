from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from google_work_agent.adapters.mcp.capabilities import (
    build_google_workspace_internal_capabilities,
)
from google_work_agent.ports.connector.migration_contracts.google_workspace_tool_contracts import (
    ToolContractViolation,
    google_workspace_tool_contract,
    list_google_workspace_tool_contracts,
    validate_tool_input,
    validate_tool_output,
)
from google_work_agent.ports.connector.migration_contracts.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)


def test_contract_catalog_matches_public_and_internal_callable_surface() -> None:
    public_names = {
        entry.tool_name for entry in build_google_workspace_tool_registry().list_entries()
    }
    internal_names = {
        capability.tool_name for capability in build_google_workspace_internal_capabilities()
    }
    contract_names = {contract.tool_name for contract in list_google_workspace_tool_contracts()}

    assert public_names.isdisjoint(internal_names)
    assert contract_names == public_names | internal_names
    assert len(contract_names) == 23


def test_public_registry_schema_hash_is_actual_contract_hash() -> None:
    registry = build_google_workspace_tool_registry()

    for entry in registry.list_entries():
        contract = google_workspace_tool_contract(entry.tool_name)
        assert entry.input_schema_version == contract.input_schema_version
        assert entry.output_schema_version == contract.output_schema_version
        assert entry.tool_schema_hash == contract.schema_hash


def test_internal_capability_schema_hash_is_actual_contract_hash() -> None:
    for capability in build_google_workspace_internal_capabilities():
        contract = google_workspace_tool_contract(capability.tool_name)
        assert capability.input_schema_version == contract.input_schema_version
        assert capability.output_schema_version == contract.output_schema_version
        assert capability.tool_schema_hash == contract.schema_hash


def test_actual_schema_change_changes_schema_hash() -> None:
    contract = google_workspace_tool_contract("gmail_get_thread")
    changed_input = deepcopy(contract.input_schema)
    properties = changed_input["properties"]
    assert isinstance(properties, dict)
    properties["new_required_identity"] = {"type": "string"}
    required = changed_input["required"]
    assert isinstance(required, list)
    required.append("new_required_identity")

    changed = replace(contract, input_schema=changed_input)

    assert changed.schema_hash != contract.schema_hash


def test_missing_required_input_is_rejected() -> None:
    with pytest.raises(ToolContractViolation) as captured:
        validate_tool_input("gmail_get_thread", {})

    assert captured.value.phase == "input"
    assert any("thread_id is required" in error for error in captured.value.errors)


def test_unknown_root_input_field_is_rejected() -> None:
    with pytest.raises(ToolContractViolation) as captured:
        validate_tool_input(
            "tasks_get_task",
            {
                "task_list_id": "list-1",
                "task_id": "task-1",
                "provider_secret": "must-not-be-accepted",
            },
        )

    assert any("provider_secret is not allowed" in error for error in captured.value.errors)


def test_representative_valid_inputs_are_accepted() -> None:
    validate_tool_input(
        "calendar_list_events",
        {
            "calendar_id": "primary",
            "page_token": None,
            "page_size": 20,
            "time_min": "2026-08-20T00:00:00Z",
            "time_max": "2026-08-21T00:00:00Z",
            "single_events": True,
            "order_by": "startTime",
        },
    )
    validate_tool_input(
        "tasks_create_task",
        {
            "task_list_id": "list-1",
            "payload": {"title": "task", "recovery_fingerprint": "fp"},
            "claim_context": {"claim_version": 2},
        },
    )
    validate_tool_input(
        "gmail_send",
        {
            "draft_id": "draft-1",
            "recovery_fingerprint": "fp",
            "claim_context": {"claim_version": 2},
        },
    )


def test_representative_valid_snapshot_output_is_accepted() -> None:
    validate_tool_output(
        "tasks_get_task",
        {
            "item": {
                "fixture_snapshot_id": "snapshot-1",
                "resource_type": "task",
                "resource_id": "task-1",
                "parent_id": "list-1",
                "related_resource_ids": [],
                "version": "v1",
                "recovery_fingerprint": None,
                "payload": {"title": "Task"},
            }
        },
    )


def test_representative_valid_page_output_is_accepted() -> None:
    validate_tool_output(
        "tasks_list_tasklists",
        {
            "items": [],
            "next_page_token": None,
        },
    )


def test_malformed_output_is_rejected() -> None:
    with pytest.raises(ToolContractViolation) as captured:
        validate_tool_output(
            "gmail_get_thread",
            {"item": {"resource_id": "thread-1"}},
        )

    assert captured.value.phase == "output"
    assert captured.value.errors
