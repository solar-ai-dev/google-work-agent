from __future__ import annotations

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    workspace_runtime as server,
)
from google_work_agent.application.orchestration.task_write_semantics import (
    normalize_task_write_arguments,
)


def _arguments(payload: dict[str, object]) -> dict[str, object]:
    return {"task_list_id": "task-list-default", "payload": payload}


def test_deadline_only_preserves_deadline_in_notes_without_google_due() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments({"title": "보고서 정리", "business_deadline": "2026-08-12"}),
    )

    assert result["payload"] == {
        "title": "보고서 정리",
        "business_deadline": "2026-08-12",
        "notes": "업무 마감: 2026년 8월 12일",
    }
    assert server._task_write_body(result["payload"], title_required=True) == {  # type: ignore[arg-type]
        "title": "보고서 정리",
        "notes": "업무 마감: 2026년 8월 12일",
    }


def test_scheduled_date_maps_to_google_due_at_provider_boundary() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments({"title": "보고서 정리", "scheduled_date": "2026-08-11"}),
    )

    assert server._task_write_body(result["payload"], title_required=True) == {  # type: ignore[arg-type]
        "title": "보고서 정리",
        "due": "2026-08-11",
    }


def test_scheduled_date_and_deadline_keep_their_separate_meanings() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments(
            {
                "title": "보고서 정리",
                "scheduled_date": "2026-08-11",
                "business_deadline": "2026-08-12",
            }
        ),
    )

    payload = result["payload"]
    assert isinstance(payload, dict)
    assert payload["scheduled_date"] == "2026-08-11"
    assert payload["business_deadline"] == "2026-08-12"
    assert server._task_write_body(payload, title_required=True)["due"] == "2026-08-11"
    assert payload["notes"] == "업무 마감: 2026년 8월 12일"


def test_same_date_keeps_both_product_fields_and_existing_notes() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments(
            {
                "title": "보고서 정리",
                "scheduled_date": "2026-08-12",
                "business_deadline": "2026-08-12",
                "notes": "최종 PDF 첨부",
            }
        ),
    )

    payload = result["payload"]
    assert isinstance(payload, dict)
    assert payload["scheduled_date"] == payload["business_deadline"] == "2026-08-12"
    assert payload["notes"] == "최종 PDF 첨부\n업무 마감: 2026년 8월 12일"


def test_deadline_note_is_not_duplicated() -> None:
    result = normalize_task_write_arguments(
        "tasks_update_task",
        _arguments(
            {
                "notes": "최종 PDF 첨부\n업무 마감: 2026년 8월 12일",
                "business_deadline": "2026-08-12",
            }
        ),
    )

    payload = result["payload"]
    assert isinstance(payload, dict)
    assert payload["notes"] == "최종 PDF 첨부\n업무 마감: 2026년 8월 12일"
    assert server._task_write_body(payload, title_required=False) == {
        "notes": "최종 PDF 첨부\n업무 마감: 2026년 8월 12일",
    }


def test_legacy_due_is_rejected_before_approval() -> None:
    with pytest.raises(ValueError, match="Provider-boundary field"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"title": "기존 작업", "due": "2026-08-12"}),
        )


def test_due_and_scheduled_date_together_are_rejected() -> None:
    with pytest.raises(ValueError, match="Provider-boundary field"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"scheduled_date": "2026-08-11", "due": "2026-08-12"}),
        )


def test_task_time_range_is_rejected_before_approval() -> None:
    with pytest.raises(ValueError, match="time range is not supported"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"scheduled_date": "2026-08-11", "start_time": "22:30"}),
        )
