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


def test_unregistered_tool_lookup_fails() -> None:
    registry = build_p0_tool_registry()

    try:
        registry.require("gmail_delete_message")
    except LookupError as error:
        assert "tool not registered" in str(error)
    else:
        raise AssertionError("expected LookupError for unregistered tool")
