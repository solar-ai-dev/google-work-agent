from __future__ import annotations

from copy import deepcopy

from google_work_agent.adapters.langgraph.plan_persistence import (
    replace_llm_expected_with_deterministic_projection,
)


def _plan() -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Create task",
        "objective": "Create the requested task",
        "actions": [
            {
                "schema_version": 2,
                "action_id": "action-1",
                "position": 1,
                "effect": "CREATE",
                "tool_name": "tasks_create_task",
                "arguments": {
                    "task_list_id": "list-1",
                    "payload": {
                        "title": "Prepare report",
                        "scheduled_date": "2026-08-20",
                    },
                },
                "expected": {
                    "payload": {
                        "title": "LLM SHOULD NOT OWN THIS",
                        "resource_id": "invented-provider-id",
                    }
                },
                "evidence_refs": ["ev-1"],
                "resource_refs": [],
                "target_resource_ref_id": None,
                "depends_on_action_ids": [],
                "user_visible_reason": "User requested a task",
            }
        ],
        "evidence_refs": ["ev-1"],
        "resource_refs": [],
        "confirmation": None,
    }


def test_write_expected_is_rebuilt_from_business_arguments() -> None:
    original = _plan()
    projected = replace_llm_expected_with_deterministic_projection(original)  # type: ignore[arg-type]

    action = projected["actions"][0]
    assert action["expected"] == {
        "payload": {
            "title": "Prepare report",
            "due": "2026-08-20",
        }
    }
    assert "invented-provider-id" not in str(projected)


def test_expected_projection_does_not_mutate_llm_plan_object() -> None:
    original = _plan()
    snapshot = deepcopy(original)

    replace_llm_expected_with_deterministic_projection(original)  # type: ignore[arg-type]

    assert original == snapshot


def test_legacy_read_expected_is_left_unchanged() -> None:
    plan = _plan()
    action = plan["actions"][0]
    action["effect"] = "READ"
    action["tool_name"] = "tasks_get_task"
    action["expected"] = {"legacy": True}

    projected = replace_llm_expected_with_deterministic_projection(plan)  # type: ignore[arg-type]

    assert projected["actions"][0]["expected"] == {"legacy": True}
