from __future__ import annotations

from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)


def test_task_create_expected__maps_scheduled_date__to_provider_due() -> None:
    expected = build_expected_verification_projection(
        tool_name="tasks_create_task",
        arguments={
            "task_list_id": "list-1",
            "payload": {
                "title": "Prepare report",
                "notes": "Use Q3 numbers",
                "scheduled_date": "2026-08-20",
            },
        },
    )

    assert expected == {
        "payload": {
            "title": "Prepare report",
            "notes": "Use Q3 numbers",
            "due": "2026-08-20",
        }
    }


def test_expected_never__contains_provider__generated_identity() -> None:
    for tool_name, arguments in (
        (
            "gmail_create_draft",
            {"payload": {"to": ["a@example.com"], "subject": "Subject", "body": "Body"}},
        ),
        (
            "tasks_create_task",
            {"task_list_id": "list-1", "payload": {"title": "Task"}},
        ),
        (
            "calendar_create_event",
            {
                "calendar_id": "calendar-1",
                "payload": {
                    "title": "Focus",
                    "start": "2026-08-20T09:00:00+09:00",
                    "end": "2026-08-20T10:00:00+09:00",
                },
            },
        ),
    ):
        expected = build_expected_verification_projection(
            tool_name=tool_name,
            arguments=arguments,
        )
        assert "resource_id" not in expected
        assert "version" not in expected


def test_gmail_send_expected__matches_fresh_sent__message_lookup_surface() -> None:
    assert build_expected_verification_projection(
        tool_name="gmail_send",
        arguments={"draft_id": "draft-1"},
    ) == {"resource_type": "gmail_message"}


def test_gmail_draft_actual__normalizes_recipient_list__to_metadata_header() -> None:
    actual = normalize_actual_verification_projection(
        tool_name="gmail_create_draft",
        actual={"payload": {"to": ["a@example.com", "b@example.com"]}},
    )

    assert actual == {"payload": {"to": "a@example.com, b@example.com"}}


def test_calendar_expected_omits__fields_current_verification__snapshot_cannot_observe() -> None:
    expected = build_expected_verification_projection(
        tool_name="calendar_create_event",
        arguments={
            "calendar_id": "calendar-1",
            "payload": {
                "title": "Focus",
                "start": "2026-08-20T09:00:00+09:00",
                "end": "2026-08-20T10:00:00+09:00",
                "description": "Deep work",
                "attendees": ["a@example.com"],
            },
        },
    )

    assert expected == {
        "payload": {
            "title": "Focus",
            "start": "2026-08-20T09:00:00+09:00",
            "end": "2026-08-20T10:00:00+09:00",
        }
    }


def test_delete_expected__is_absence__only() -> None:
    assert build_expected_verification_projection(
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "list-1", "task_id": "task-1"},
    ) == {"absent": True}


def test_subset_compare__ignores_extra__provider_metadata() -> None:
    expected = {"payload": {"title": "Prepare report"}}
    actual = {
        "resource_type": "task",
        "resource_id": "provider-generated-id",
        "version": "provider-version",
        "payload": {
            "title": "Prepare report",
            "status": "needsAction",
        },
    }

    assert calculate_verification_subset_diff(expected, actual) == []


def test_subset_compare__still_detects_expected__business_field_mismatch() -> None:
    diff = calculate_verification_subset_diff(
        {"payload": {"title": "Prepare report"}},
        {"payload": {"title": "Different title"}},
    )

    assert diff == [
        {
            "path": "$.payload.title",
            "expected": "Prepare report",
            "actual": "Different title",
        }
    ]


def test_task_due__actual_is_normalized__to_product_date() -> None:
    actual = normalize_actual_verification_projection(
        tool_name="tasks_create_task",
        actual={
            "payload": {
                "title": "Prepare report",
                "due": "2026-08-20T00:00:00.000Z",
            }
        },
    )

    assert actual["payload"] == {
        "title": "Prepare report",
        "due": "2026-08-20",
    }


def test_task_create_actual__strips_only_server__generated_recovery_marker() -> None:
    actual = normalize_actual_verification_projection(
        tool_name="tasks_create_task",
        actual={
            "payload": {
                "title": "Prepare report",
                "notes": "Use Q3 numbers\n\n\u200bgwa-recovery-fingerprint:abc123",
            }
        },
    )

    assert actual["payload"] == {
        "title": "Prepare report",
        "notes": "Use Q3 numbers",
    }
