"""Google Workspace connector-local signed tool registry."""

from __future__ import annotations

from google_work_agent.domain.enums import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)
from google_work_agent.domain.tool_registry import SignedToolRegistry, ToolRegistryEntry

_GMAIL_DRAFT_MODIFY_FIELDS: frozenset[str] = frozenset({"to", "cc", "subject", "body"})
_TASK_MODIFY_FIELDS: frozenset[str] = frozenset({"title", "notes", "due"})
_CALENDAR_EVENT_MODIFY_FIELDS: frozenset[str] = frozenset({"title", "start", "end", "description"})


def build_google_workspace_tool_registry() -> SignedToolRegistry:
    """Build the connector-local Gmail, Tasks, and Calendar registry."""

    return SignedToolRegistry(
        entries=(
            _read_tool(tool_name="calendar_get_event", scope="calendar.events"),
            _create_tool(
                tool_name="calendar_create_event",
                scope="calendar.events",
                modify_patchable_fields=_CALENDAR_EVENT_MODIFY_FIELDS,
            ),
            _delete_tool(tool_name="calendar_delete_event", scope="calendar.events"),
            _read_tool(tool_name="calendar_list_calendars", scope="calendarlist.readonly"),
            _read_tool(tool_name="calendar_list_events", scope="calendar.events"),
            _read_tool(tool_name="calendar_query_freebusy", scope="calendar.events.freebusy"),
            _update_tool(
                tool_name="calendar_update_event",
                scope="calendar.events",
                modify_patchable_fields=_CALENDAR_EVENT_MODIFY_FIELDS,
            ),
            _create_tool(
                tool_name="gmail_create_draft",
                scope="gmail.compose",
                modify_patchable_fields=_GMAIL_DRAFT_MODIFY_FIELDS,
            ),
            _read_tool(tool_name="gmail_get_draft", scope="gmail.compose"),
            _read_tool(tool_name="gmail_get_message", scope="gmail.readonly"),
            _read_tool(tool_name="gmail_get_thread", scope="gmail.readonly"),
            _read_tool(tool_name="gmail_search_threads", scope="gmail.readonly"),
            _send_tool(tool_name="gmail_send", scope="gmail.compose"),
            _update_tool(
                tool_name="gmail_update_draft",
                scope="gmail.compose",
                modify_patchable_fields=_GMAIL_DRAFT_MODIFY_FIELDS,
            ),
            _create_tool(
                tool_name="tasks_create_task",
                scope="tasks",
                modify_patchable_fields=_TASK_MODIFY_FIELDS,
            ),
            _read_tool(tool_name="tasks_get_task", scope="tasks"),
            _read_tool(tool_name="tasks_list_tasklists", scope="tasks"),
            _read_tool(tool_name="tasks_list_tasks", scope="tasks"),
            _update_tool(
                tool_name="tasks_update_task",
                scope="tasks",
                modify_patchable_fields=_TASK_MODIFY_FIELDS,
            ),
            _delete_tool(tool_name="tasks_delete_task", scope="tasks"),
        )
    )


def _read_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        effect_type=EffectType.READ,
        approval_requirement=ApprovalRequirement.NONE,
        verification_policy=VerificationPolicy.NONE,
        recovery_policy=RecoveryPolicy.NONE,
        scope=scope,
        retryable=True,
    )


def _create_tool(
    *, tool_name: str, scope: str, modify_patchable_fields: frozenset[str] = frozenset()
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        effect_type=EffectType.CREATE,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.GET_COMPARE,
        recovery_policy=RecoveryPolicy.RESOURCE_SEARCH,
        scope=scope,
        retryable=False,
        modify_patchable_fields=modify_patchable_fields,
    )


def _update_tool(
    *, tool_name: str, scope: str, modify_patchable_fields: frozenset[str] = frozenset()
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        effect_type=EffectType.UPDATE,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.GET_COMPARE,
        recovery_policy=RecoveryPolicy.GET_TARGET,
        scope=scope,
        retryable=False,
        modify_patchable_fields=modify_patchable_fields,
    )


def _send_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        effect_type=EffectType.SEND,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.SENT_LOOKUP,
        recovery_policy=RecoveryPolicy.MESSAGE_SEARCH,
        scope=scope,
        retryable=False,
    )


def _delete_tool(*, tool_name: str, scope: str) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_name=tool_name,
        effect_type=EffectType.DELETE,
        approval_requirement=ApprovalRequirement.REQUIRED,
        verification_policy=VerificationPolicy.GET_ABSENT,
        recovery_policy=RecoveryPolicy.GET_TARGET,
        scope=scope,
        retryable=False,
    )
