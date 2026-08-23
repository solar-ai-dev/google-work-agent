from google_work_agent.domain import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
    build_p0_tool_registry,
)


def test_p0_tool_registry_contains_only_allowed_tools() -> None:
    registry = build_p0_tool_registry()

    names = {entry.tool_name for entry in registry.list_entries()}

    assert names == {
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
    }
    assert "tasks_complete_task" not in names


def test_read_tool_registry_contract_matches_policy() -> None:
    entry = build_p0_tool_registry().require("gmail_get_thread")

    assert entry.effect_type is EffectType.READ
    assert entry.approval_requirement is ApprovalRequirement.NONE
    assert entry.verification_policy is VerificationPolicy.NONE
    assert entry.recovery_policy is RecoveryPolicy.NONE
    assert entry.retryable is True


def test_write_tool_registry_contract_matches_policy() -> None:
    create_entry = build_p0_tool_registry().require("gmail_create_draft")
    update_entry = build_p0_tool_registry().require("calendar_update_event")
    send_entry = build_p0_tool_registry().require("gmail_send")
    delete_entry = build_p0_tool_registry().require("calendar_delete_event")

    assert create_entry.effect_type is EffectType.CREATE
    assert create_entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert create_entry.verification_policy is VerificationPolicy.GET_COMPARE
    assert create_entry.recovery_policy is RecoveryPolicy.RESOURCE_SEARCH
    assert create_entry.retryable is False
    assert send_entry.scope == "gmail.compose"

    assert update_entry.effect_type is EffectType.UPDATE
    assert update_entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert update_entry.verification_policy is VerificationPolicy.GET_COMPARE
    assert update_entry.recovery_policy is RecoveryPolicy.GET_TARGET
    assert update_entry.retryable is False

    assert send_entry.effect_type is EffectType.SEND
    assert send_entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert send_entry.verification_policy is VerificationPolicy.SENT_LOOKUP
    assert send_entry.recovery_policy is RecoveryPolicy.MESSAGE_SEARCH
    assert send_entry.retryable is False

    assert delete_entry.effect_type is EffectType.DELETE
    assert delete_entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert delete_entry.verification_policy is VerificationPolicy.GET_ABSENT
    assert delete_entry.recovery_policy is RecoveryPolicy.GET_TARGET
    assert delete_entry.retryable is False


def test_task_delete_tool_registry_contract_matches_policy() -> None:
    entry = build_p0_tool_registry().require("tasks_delete_task")

    assert entry.effect_type is EffectType.DELETE
    assert entry.approval_requirement is ApprovalRequirement.REQUIRED
    assert entry.verification_policy is VerificationPolicy.GET_ABSENT
    assert entry.recovery_policy is RecoveryPolicy.GET_TARGET
    assert entry.retryable is False


def test_modify_patchable_fields_match_fn_052_exactly() -> None:
    """FN-042A/FN-052 fix: Draft 수신자·CC·제목·본문·첨부,
    Task 제목·메모·예정일, Event 제목·시간·설명 -- and nothing else. This must
    stay narrower than what each tool's MCP dispatch call otherwise accepts
    (e.g. bcc/thread_id, Task status, Event attendees).
    """

    registry = build_p0_tool_registry()

    assert registry.require("gmail_create_draft").modify_patchable_fields == {
        "to",
        "cc",
        "subject",
        "body",
        "attachments",
    }
    assert registry.require("gmail_update_draft").modify_patchable_fields == {
        "to",
        "cc",
        "subject",
        "body",
        "attachments",
    }
    assert registry.require("tasks_create_task").modify_patchable_fields == {
        "title",
        "notes",
        "due",
    }
    assert registry.require("tasks_update_task").modify_patchable_fields == {
        "title",
        "notes",
        "due",
    }
    assert registry.require("calendar_create_event").modify_patchable_fields == {
        "title",
        "start",
        "end",
        "description",
    }
    assert registry.require("calendar_update_event").modify_patchable_fields == {
        "title",
        "start",
        "end",
        "description",
    }

    # Target-only tools have no FN-052-authorized business field.
    for tool_name in ("gmail_send", "calendar_delete_event", "tasks_delete_task"):
        assert registry.require(tool_name).modify_patchable_fields == frozenset()

    # Fields the underlying MCP dispatch accepts but FN-042A/FN-052 do not
    # authorize for user Modify must stay excluded.
    excluded = {"bcc", "thread_id", "status", "attendees"}
    for tool_name in (
        "gmail_create_draft",
        "gmail_update_draft",
        "tasks_create_task",
        "tasks_update_task",
        "calendar_create_event",
        "calendar_update_event",
    ):
        assert registry.require(tool_name).modify_patchable_fields.isdisjoint(excluded)


def test_unregistered_tool_lookup_fails() -> None:
    registry = build_p0_tool_registry()

    for tool_name in (
        "gmail_delete_message",
        "calendar_delete_series",
    ):
        try:
            registry.require(tool_name)
        except LookupError as error:
            assert "tool not registered" in str(error)
        else:
            raise AssertionError(f"expected LookupError for unregistered tool: {tool_name}")
