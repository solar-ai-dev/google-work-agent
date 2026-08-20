from typing import cast

import pytest

from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    connector_ids_from_frozen_routes,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1


def _plan() -> ActionPlanDraftV1:
    return cast(
        ActionPlanDraftV1,
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": "plan-1",
            "summary": "summary",
            "objective": "objective",
            "actions": [
                {
                    "schema_version": 2,
                    "action_id": "action-1",
                    "position": 1,
                    "effect": "CREATE",
                    "tool_name": "github_create_issue",
                    "arguments": {"title": "x"},
                    "expected": {},
                    "evidence_refs": [],
                    "resource_refs": [],
                    "target_resource_ref_id": None,
                    "depends_on_action_ids": [],
                    "user_visible_reason": "reason",
                }
            ],
            "evidence_refs": [],
            "resource_refs": [],
            "confirmation": None,
        },
    )


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "tool_route_plan": {
                "schema_version": 2,
                "input_plan": {"schema_version": 1, "meta": {}, "input_routes": []},
                "output_plan": {
                    "schema_version": 1,
                    "meta": {},
                    "output_mode": "ACTION",
                    "output_routes": [
                        {
                            "route_id": "route-1",
                            "resource_type": "TASK",
                            "connector_id": "github",
                            "effect": "CREATE",
                            "selected_tool_id": "github_create_issue",
                            "reason_codes": [],
                        }
                    ],
                },
                "tool_registry_version": "test",
            }
        },
    )


def test_connector_id_is_rejoined_from_frozen_output_route() -> None:
    assert connector_ids_from_frozen_routes(state=_state(), plan_draft=_plan()) == {
        "action-1": "github"
    }


def test_connector_binding_fails_closed_on_tool_drift() -> None:
    plan = _plan()
    plan["actions"][0]["tool_name"] = "tasks_create_task"

    with pytest.raises(ValueError, match="does not match frozen route"):
        connector_ids_from_frozen_routes(state=_state(), plan_draft=plan)


def test_connector_binding_fails_closed_when_connector_is_missing() -> None:
    state = _state()
    output_plan = cast(dict[str, object], state["tool_route_plan"])["output_plan"]
    route = cast(dict[str, object], cast(dict[str, object], output_plan)["output_routes"])[0]
    cast(dict[str, object], route)["connector_id"] = ""

    with pytest.raises(ValueError, match="connector_id is required"):
        connector_ids_from_frozen_routes(state=state, plan_draft=_plan())
