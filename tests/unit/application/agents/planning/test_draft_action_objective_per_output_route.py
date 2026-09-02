from collections.abc import Mapping

from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    draft_action_objective_per_output_route,
)


def test_objective_prompt_is__route_bounded_and__receives_no_tool_schema() -> None:
    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == "planning.draft_action_objective_per_output_route"
        assert "tool_schema" not in prompt_input
        assert "work_analysis" not in prompt_input
        route = prompt_input["output_route"]
        assert isinstance(route, Mapping)
        return {
            "schema_version": 1,
            "route_id": route["route_id"],
            "objective": "Create the requested task",
            "target_semantics": "TASK",
            "scope_constraints": ["create only"],
            "evidence_refs": ["e1"],
        }

    result = draft_action_objective_per_output_route(
        [{"route_id": "r1", "selected_tool_id": "tasks_create_task"}],
        user_request="Create a task",
        request_intent={"goal": "create task"},
        work_analysis=None,
        evidence=[{"evidence_ref": "e1"}],
        invoke=invoke,
    )
    assert result[0]["route_id"] == "r1"
    assert result[0]["target_semantics"] == "TASK"
