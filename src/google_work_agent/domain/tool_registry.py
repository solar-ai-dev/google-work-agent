"""Signed tool registry contract for the P0 product core."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps

from google_work_agent.domain.enums import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)

DEFAULT_POLICY_VERSION = "2026-08-06.p0"
DEFAULT_TOOL_SCHEMA_VERSION = "v1"

# FN-052 (01-a-functional-definition.md) fixes the exact business fields a
# user may change through Action Modify: "Draft 수신자·CC·제목·본문, Task
# 제목·메모·예정일, Event 제목·시간·설명." This is a *product/policy* surface,
# deliberately narrower than what a tool's MCP dispatch call otherwise accepts
# (e.g. gmail_create_draft/gmail_update_draft also carry bcc/thread_id/
# attachments at Plan-creation time, tasks_update_task also carries a
# completion `status`, calendar_update_event also carries `attendees`). Do
# not widen these sets to match tool dispatch capability -- that would grant
# more Modify authority than FN-052 defines. Target/container identity
# fields (draft_id, task_id, event_id, task_list_id, calendar_id) are never
# included: ModifyAction must never be able to retarget an existing resource.
# DELETE and SEND tools have no FN-052 patchable fields: their only argument
# is the target itself.
_GMAIL_DRAFT_MODIFY_FIELDS: frozenset[str] = frozenset({"to", "cc", "subject", "body"})
_TASK_MODIFY_FIELDS: frozenset[str] = frozenset({"title", "notes", "due"})
_CALENDAR_EVENT_MODIFY_FIELDS: frozenset[str] = frozenset({"title", "start", "end", "description"})


@dataclass(frozen=True, slots=True)
class ToolRegistryEntry:
    """Deterministic policy snapshot for one registered tool."""

    tool_name: str
    effect_type: EffectType
    approval_requirement: ApprovalRequirement
    verification_policy: VerificationPolicy
    recovery_policy: RecoveryPolicy
    scope: str
    retryable: bool
    input_schema_version: str = DEFAULT_TOOL_SCHEMA_VERSION
    output_schema_version: str = DEFAULT_TOOL_SCHEMA_VERSION
    registry_version: str = DEFAULT_POLICY_VERSION
    tool_schema_hash: str = ""
    # FN-052 Action Modify authority for this tool -- NOT the tool's full MCP
    # dispatch-time mutable capability. See the module-level comment above.
    modify_patchable_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.tool_schema_hash:
            return
        payload = dumps(
            {
                "tool_name": self.tool_name,
                "effect_type": self.effect_type.value,
                "approval_requirement": self.approval_requirement.value,
                "verification_policy": self.verification_policy.value,
                "recovery_policy": self.recovery_policy.value,
                "scope": self.scope,
                "retryable": self.retryable,
                "input_schema_version": self.input_schema_version,
                "output_schema_version": self.output_schema_version,
                "registry_version": self.registry_version,
                "modify_patchable_fields": sorted(self.modify_patchable_fields),
            },
            sort_keys=True,
        ).encode("utf-8")
        object.__setattr__(self, "tool_schema_hash", sha256(payload).hexdigest())


class SignedToolRegistry:
    """Immutable lookup wrapper over a fixed tool registry snapshot."""

    def __init__(self, entries: tuple[ToolRegistryEntry, ...]) -> None:
        self._entries = {entry.tool_name: entry for entry in entries}
        if len(self._entries) != len(entries):
            raise ValueError("tool registry contains duplicate tool_name values")

    def get(self, tool_name: str) -> ToolRegistryEntry | None:
        """Return the registry entry for a tool, if registered."""

        return self._entries.get(tool_name)

    def require(self, tool_name: str) -> ToolRegistryEntry:
        """Return the registry entry or fail for unregistered tools."""

        entry = self.get(tool_name)
        if entry is None:
            raise LookupError(f"tool not registered: {tool_name}")
        return entry

    def list_entries(self) -> tuple[ToolRegistryEntry, ...]:
        """Return the full registry snapshot in sorted tool-name order."""

        return tuple(sorted(self._entries.values(), key=lambda entry: entry.tool_name))


def build_p0_tool_registry() -> SignedToolRegistry:
    """Build the fixed P0 signed tool registry snapshot."""

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
