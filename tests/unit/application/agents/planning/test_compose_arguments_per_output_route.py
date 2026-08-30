from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
    resolve_default_container,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)

ROUTE = {
    "route_id": "r1",
    "resource_type": "TASK",
    "connector_id": "google_workspace",
    "effect": "CREATE",
    "selected_tool_id": "tasks_create_task",
    "reason_codes": [],
}
OBJECTIVE = {
    "schema_version": 1,
    "route_id": "r1",
    "objective": "Create task",
    "target_semantics": "TASK",
    "scope_constraints": ["create only"],
    "evidence_refs": ["e1"],
}


def test_argument_prompt_receives_only_selected_bound_tool_schema() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )

    def invoke(_prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert set(prompt_input) == {"output_route", "action_objective", "tool_schema", "evidence"}
        assert prompt_input["tool_schema"]["properties"]["task_list_id"]["const"] == "list-1"  # type: ignore[index]
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"title": "Report"}},
            "evidence_refs": ["e1"],
        }

    result = compose_arguments_per_output_route(
        [ROUTE],  # type: ignore[list-item]
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=invoke,
    )
    assert result[0]["arguments"]["task_list_id"] == "list-1"


def test_argument_candidate_cannot_override_bound_container() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )
    with pytest.raises(PlanningArgumentBindingError, match="immutable"):
        compose_arguments_per_output_route(
            [ROUTE],  # type: ignore[list-item]
            objectives=[OBJECTIVE],  # type: ignore[list-item]
            bound_tool_schemas=[bound],
            evidence=[{"evidence_ref": "e1"}],
            invoke=lambda *_: {
                "schema_version": 1,
                "route_id": "r1",
                "arguments": {"task_list_id": "other", "payload": {"title": "Report"}},
                "evidence_refs": ["e1"],
            },
        )
