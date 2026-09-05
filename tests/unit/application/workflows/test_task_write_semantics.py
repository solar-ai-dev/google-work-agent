from __future__ import annotations

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as server,
)
from google_work_agent.application.agents.planning.validate_plan import (
    normalize_task_write_arguments,
)


def _arguments(payload: dict[str, object]) -> dict[str, object]:
    return {"task_list_id": "task-list-default", "payload": payload}


def test_deadline_only_preserves__deadline_in_notes__without_google_due() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments({"title": "보고서 정리", "business_deadline": "2026-08-12"}),
    )

    assert result["payload"] == {
        "title": "보고서 정리",
        "business_deadline": "2026-08-12",
        "notes": "업무 마감: 2026년 8월 12일",
    }
    assert server._task_write_body(result["payload"], title_required=True) == {
        "title": "보고서 정리",
        "notes": "업무 마감: 2026년 8월 12일",
    }


def test_scheduled_date_maps__to_google_due__at_provider_boundary() -> None:
    result = normalize_task_write_arguments(
        "tasks_create_task",
        _arguments({"title": "보고서 정리", "scheduled_date": "2026-08-11"}),
    )

    assert server._task_write_body(result["payload"], title_required=True) == {  # type: ignore[arg-type]
        "title": "보고서 정리",
        "due": "2026-08-11T00:00:00Z",
    }


@pytest.mark.parametrize("value", ["2026-02-30", "20260907", "2026-09-07T14:00:00+09:00"])
def test_invalid_scheduled_date_is_rejected_before_provider_write(value: str) -> None:
    with pytest.raises(server._WorkspaceToolError, match="INVALID_ARGUMENT"):
        server._task_write_body({"title": "Report", "scheduled_date": value}, title_required=True)


def test_scheduled_date__and_deadline_keep__their_separate_meanings() -> None:
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
    assert server._task_write_body(payload, title_required=True)["due"] == "2026-08-11T00:00:00Z"
    assert payload["notes"] == "업무 마감: 2026년 8월 12일"


def test_same_date_keeps__both_product_fields__and_existing_notes() -> None:
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


def test_deadline_note__is_not__duplicated() -> None:
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


def test_legacy_due__is_rejected__before_approval() -> None:
    with pytest.raises(ValueError, match="Provider-boundary field"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"title": "기존 작업", "due": "2026-08-12"}),
        )


def test_due_and__scheduled_date__together_are_rejected() -> None:
    with pytest.raises(ValueError, match="Provider-boundary field"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"scheduled_date": "2026-08-11", "due": "2026-08-12"}),
        )


def test_task_time__range_is__rejected_before_approval() -> None:
    with pytest.raises(ValueError, match="time range is not supported"):
        normalize_task_write_arguments(
            "tasks_create_task",
            _arguments({"scheduled_date": "2026-08-11", "start_time": "22:30"}),
        )
