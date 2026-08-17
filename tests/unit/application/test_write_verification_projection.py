from __future__ import annotations

from google_work_agent.application.write_verification_projection import (
    build_expected_verification_projection,
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)


def test_task_create_expected_maps_scheduled_date_to_provider_due() -> None:
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


def test_expected_never_contains_provider_generated_identity() -> None:
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


def test_gmail_send_expected_is_deterministic_from_approved_draft_id() -> None:
    assert build_expected_verification_projection(
        tool_name="gmail_send",
        arguments={"draft_id": "draft-1"},
    ) == {"payload": {"sent": True, "draft_id": "draft-1"}}


def test_delete_expected_is_absence_only() -> None:
    assert build_expected_verification_projection(
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "list-1", "task_id": "task-1"},
    ) == {"absent": True}


def test_subset_compare_ignores_extra_provider_metadata() -> None:
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


def test_subset_compare_still_detects_expected_business_field_mismatch() -> None:
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


def test_task_due_actual_is_normalized_to_product_date() -> None:
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
