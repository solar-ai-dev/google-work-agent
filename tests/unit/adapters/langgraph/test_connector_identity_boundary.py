from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.plan_persistence import (
    connector_ids_for_read_actions_from_frozen_routes,
    connector_ids_from_frozen_routes,
    target_resource_connector_ids_from_actions,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.orchestration.handoff_contracts import ActionPlanDraftV1


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


def _read_plan() -> ActionPlanDraftV1:
    plan = _plan()
    action = plan["actions"][0]
    action["effect"] = "READ"
    action["tool_name"] = "tasks_list_tasks"
    return plan


def _read_state() -> GraphState:
    state = _state()
    route_plan = cast(dict[str, object], state["tool_route_plan"])
    route_plan["input_plan"] = {
        "schema_version": 1,
        "meta": {},
        "input_routes": [
            {
                "route_id": "read-route-1",
                "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True,
                "reason_codes": [],
            }
        ],
    }
    return state


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
    route_plan = cast(dict[str, object], state["tool_route_plan"])
    output_plan = cast(dict[str, object], route_plan["output_plan"])
    routes = cast(list[dict[str, object]], output_plan["output_routes"])
    routes[0]["connector_id"] = ""

    with pytest.raises(ValueError, match="connector_id is required"):
        connector_ids_from_frozen_routes(state=state, plan_draft=_plan())


def test_target_resource_connectors_are_bound_per_action() -> None:
    plan = _plan()
    first = plan["actions"][0]
    first["target_resource_ref_id"] = "task:123"
    plan["actions"].append(
        {
            **first,
            "action_id": "action-2",
            "position": 2,
            "tool_name": "github_update_issue",
            "target_resource_ref_id": "issue:456",
        }
    )

    assert target_resource_connector_ids_from_actions(
        plan_draft=plan,
        action_connector_ids={
            "action-1": "google_workspace",
            "action-2": "github",
        },
    ) == {
        "task:123": "google_workspace",
        "issue:456": "github",
    }


def test_target_resource_binding_fails_closed_on_cross_connector_handle_reuse() -> None:
    plan = _plan()
    first = plan["actions"][0]
    first["target_resource_ref_id"] = "shared:123"
    plan["actions"].append(
        {
            **first,
            "action_id": "action-2",
            "position": 2,
            "target_resource_ref_id": "shared:123",
        }
    )

    with pytest.raises(ValueError, match="multiple connectors"):
        target_resource_connector_ids_from_actions(
            plan_draft=plan,
            action_connector_ids={
                "action-1": "google_workspace",
                "action-2": "github",
            },
        )


def test_read_connector_id_is_rejoined_from_frozen_input_route() -> None:
    assert connector_ids_for_read_actions_from_frozen_routes(
        state=_read_state(), plan_draft=_read_plan()
    ) == {"action-1": "google_workspace"}


def test_read_connector_binding_fails_closed_without_matching_route() -> None:
    plan = _read_plan()
    plan["actions"][0]["tool_name"] = "gmail_get_message"

    with pytest.raises(ValueError, match="exactly one frozen connector"):
        connector_ids_for_read_actions_from_frozen_routes(state=_read_state(), plan_draft=plan)


def test_read_connector_binding_fails_closed_on_ambiguous_connectors() -> None:
    state = _read_state()
    route_plan = cast(dict[str, object], state["tool_route_plan"])
    input_plan = cast(dict[str, object], route_plan["input_plan"])
    routes = cast(list[dict[str, object]], input_plan["input_routes"])
    routes.append(
        {
            "route_id": "read-route-2",
            "resource_type": "TASK",
            "connector_id": "github",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": [],
        }
    )

    with pytest.raises(ValueError, match="exactly one frozen connector"):
        connector_ids_for_read_actions_from_frozen_routes(state=state, plan_draft=_read_plan())
