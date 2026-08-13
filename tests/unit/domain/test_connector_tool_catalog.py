import pytest

from google_work_agent.domain import ConnectorToolCatalog, SignedToolRegistry, ToolRegistryEntry
from google_work_agent.domain.enums import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)


def test_catalog_looks_up_existing_google_workspace_tool_id() -> None:
    catalog = ConnectorToolCatalog()
    catalog.register(
        connector_id="google_workspace",
        registry=build_google_workspace_tool_registry(),
    )

    entry = catalog.require(connector_id="google_workspace", tool_id="gmail_send")

    assert entry.tool_name == "gmail_send"
    assert catalog.list_connector_ids() == ("google_workspace",)


def test_catalog_rejects_duplicate_connector_registry() -> None:
    catalog = ConnectorToolCatalog()
    registry = build_google_workspace_tool_registry()
    catalog.register(connector_id="google_workspace", registry=registry)

    with pytest.raises(ValueError, match="already registered"):
        catalog.register(connector_id="google_workspace", registry=registry)


def test_catalog_rejects_unknown_connector_and_tool() -> None:
    catalog = ConnectorToolCatalog()
    catalog.register(
        connector_id="google_workspace",
        registry=build_google_workspace_tool_registry(),
    )

    with pytest.raises(LookupError, match="registry not registered"):
        catalog.require(connector_id="unknown", tool_id="gmail_send")
    with pytest.raises(LookupError, match="tool not registered"):
        catalog.require(connector_id="google_workspace", tool_id="unknown")


def test_connector_local_registry_rejects_duplicate_tool_id() -> None:
    entry = _entry("gmail_send")

    with pytest.raises(ValueError, match="duplicate tool_name"):
        SignedToolRegistry((entry, entry))


def test_existing_p0_public_tool_names_are_unchanged() -> None:
    names = tuple(
        entry.tool_name for entry in build_google_workspace_tool_registry().list_entries()
    )

    assert names == (
        "calendar_create_event",
        "calendar_delete_event",
        "calendar_get_event",
        "calendar_list_calendars",
        "calendar_list_events",
        "calendar_query_freebusy",
        "calendar_update_event",
        "gmail_create_draft",
        "gmail_get_draft",
        "gmail_get_message",
        "gmail_get_thread",
        "gmail_search_threads",
        "gmail_send",
        "gmail_update_draft",
        "tasks_create_task",
        "tasks_delete_task",
        "tasks_get_task",
        "tasks_list_tasklists",
        "tasks_list_tasks",
        "tasks_update_task",
    )


def _entry(tool_name: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        resource_type="TASK",
        effect_type=EffectType.READ,
        approval_requirement=ApprovalRequirement.NONE,
        verification_policy=VerificationPolicy.NONE,
        recovery_policy=RecoveryPolicy.NONE,
        scope="test",
        retryable=True,
    )
