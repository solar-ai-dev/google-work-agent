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


def test_exact_calendar_create__materializes_objective__without_llm() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "calendar-route",
                "resource_type": "CALENDAR_EVENT",
                "effect": "CREATE",
                "selected_tool_id": "calendar_create_event",
            }
        ],
        user_request="create an event",
        request_intent={
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "[GWA OPT] Calendar 42"},
                {"kind": "DATE", "field": "date", "value": "2026-09-08"},
                {"kind": "TIME", "field": "start_time", "value": "15:00"},
                {"kind": "TIME", "field": "end_time", "value": "15:30"},
                {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
            ],
        },
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "user-message-1",
                "origin_type": "USER_MESSAGE",
                "kind": "USER_REQUEST",
            }
        ],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["route_id"] == "calendar-route"
    assert result[0]["target_semantics"] == "CALENDAR_EVENT"
    assert "title: [GWA OPT] Calendar 42" in result[0]["scope_constraints"]
    assert result[0]["evidence_refs"] == ["user-message-1"]


def test_exact_task_create__materializes_objective__without_llm() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "task-route",
                "resource_type": "TASK",
                "effect": "CREATE",
                "selected_tool_id": "tasks_create_task",
            }
        ],
        user_request="create a task",
        request_intent={
            "requested_resource_hints": ["TASK"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "title", "value": "Submit report"}
            ],
        },
        work_analysis=None,
        evidence=[{"evidence_id": "user-message-1"}],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["target_semantics"] == "TASK"
    assert result[0]["scope_constraints"] == ["title: Submit report"]
    assert result[0]["evidence_refs"] == ["user-message-1"]


def test_calendar_create_objective__avoids_repeating__semantic_field_alias_work() -> None:
    result = draft_action_objective_per_output_route(
        [
            {
                "route_id": "calendar-route",
                "resource_type": "CALENDAR_EVENT",
                "effect": "CREATE",
                "selected_tool_id": "calendar_create_event",
            }
        ],
        user_request="create an event",
        request_intent={
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "requested_effect_hints": ["CREATE"],
            "ambiguity": {"requires_confirmation": False},
            "constraints": [
                {"kind": "RESOURCE", "field": "calendar_id", "value": "Project"},
                {"kind": "DATE", "field": "event_start_datetime", "value": "2026-09-11T15:00"},
                {"kind": "DATE", "field": "event_end_datetime", "value": "2026-09-11T15:30"},
                {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
            ],
        },
        work_analysis=None,
        evidence=[],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["target_semantics"] == "CALENDAR_EVENT"
    assert "calendar_id: Project" in result[0]["scope_constraints"]
