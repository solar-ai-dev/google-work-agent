from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.plan_persistence import (
    connector_ids_from_frozen_routes,
    expected_for_action,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
    PlannedActionV2,
)


def _action() -> PlannedActionV2:
    return {
        "action_id": "action-1",
        "route_id": "route-1",
        "tool_id": "tasks_create_task",
        "effect": "CREATE",
        "arguments": {
            "task_list_id": "list-1",
            "payload": {"title": "Prepare report", "scheduled_date": "2026-08-20"},
        },
        "evidence_refs": ["evidence-1"],
        "depends_on_action_ids": [],
    }


def _plan() -> ActionPlanDraftV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "plan-1", "revision": 1, "based_on": []},
        "actions": [_action()],
    }


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "tool_route_plan": {
                "output_plan": {
                    "output_mode": "ACTION",
                    "output_routes": [
                        {
                            "route_id": "route-1",
                            "connector_id": "google_workspace",
                            "effect": "CREATE",
                            "selected_tool_id": "tasks_create_task",
                        }
                    ],
                }
            }
        },
    )


def test_current_plan__joins_frozen_route__and_builds_expected() -> None:
    action = _action()

    assert connector_ids_from_frozen_routes(state=_state(), plan=_plan()) == {
        "action-1": "google_workspace"
    }
    assert expected_for_action(action) == {
        "payload": {"title": "Prepare report", "due": "2026-08-20"}
    }


@pytest.mark.parametrize("field", ["route_id", "tool_id", "effect"])
def test_current_plan__fails_closed_on__frozen_route_drift(field: str) -> None:
    plan = _plan()
    plan["actions"][0][field] = "drift"  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="does not match frozen route"):
        connector_ids_from_frozen_routes(state=_state(), plan=plan)
