import pytest

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)
from google_work_agent.application.orchestration.planning_arguments import (
    DefaultContainerResolver,
    PlanningArgumentBindingError,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    materialize_action_seeds,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)


def _task_create_route() -> OutputToolRouteV1:
    return {
        "route_id": "route-task-create",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": ["USER_REQUEST"],
    }


def test_action_argument_candidate_requires_evidence() -> None:
    route = _task_create_route()
    bound = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "list-default"
    ).bind_selected_tool_schema(
        route=route,
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="at least one evidence ref"):
        validate_tool_argument_candidate_v1(
            {
                "schema_version": 1,
                "route_id": route["route_id"],
                "arguments": {"payload": {"title": "Prepare report"}},
                "evidence_refs": [],
            },
            bound_tool_schema=bound,
            allowed_evidence_refs={"ev-1"},
        )


def test_revision_materialization_preserves_preexisting_action_id_mapping() -> None:
    route = _task_create_route()
    seeds = materialize_action_seeds(
        output_routes=(route,),
        argument_candidates=(
            {
                "schema_version": 1,
                "route_id": route["route_id"],
                "arguments": {
                    "task_list_id": "list-default",
                    "payload": {"title": "Prepare revised report"},
                },
                "evidence_refs": ["ev-1"],
            },
        ),
        action_id_factory=lambda: "must-not-be-used",
        action_id_by_route={route["route_id"]: "action-existing"},
    )

    assert seeds[0]["action_id"] == "action-existing"
    assert seeds[0]["tool_id"] == "tasks_create_task"
    assert seeds[0]["effect"] == "CREATE"
