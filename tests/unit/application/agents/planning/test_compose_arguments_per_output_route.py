from collections.abc import Mapping
from typing import cast

import pytest

from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
    tool_argument_candidate_output_schema,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
    resolve_default_container,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

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


@pytest.mark.parametrize("invalid_field", ["description", "route", "container", "evidence"])
def test_inference_schema__rejects_invalid_arguments__inside_repair_boundary(
    invalid_field: str,
) -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )
    schema = tool_argument_candidate_output_schema({
        "output_route": ROUTE, "tool_schema": bound["argument_schema"],
        "evidence": [{"evidence_ref": "e1"}],
    })
    payload = {"title": "Report", "notes": "Review", "scheduled_date": "2026-09-07"}
    arguments: dict[str, object] = {"task_list_id": "list-1", "payload": payload}
    candidate: dict[str, object] = {
        "schema_version": 1, "route_id": "r1", "arguments": arguments,
        "evidence_refs": ["e1"],
    }
    assert validate_output_schema(candidate, schema.json_schema) == []
    if invalid_field == "description":
        payload["description"] = payload.pop("notes")
    elif invalid_field == "route":
        candidate["route_id"] = "other-route"
    elif invalid_field == "container":
        arguments["task_list_id"] = "other-list"
    else:
        candidate["evidence_refs"] = ["unavailable"]
    assert validate_output_schema(candidate, schema.json_schema)


def test_argument_prompt__receives_only_selected__bound_tool_schema() -> None:
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
        [ROUTE],
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        evidence=[{"evidence_ref": "e1"}],
        invoke=cast(PlanningSemanticInvoker, invoke),
    )
    assert result[0]["arguments"]["task_list_id"] == "list-1"


def test_argument_candidate__cannot_override__bound_container() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="list-1",
    )
    with pytest.raises(PlanningArgumentBindingError, match="immutable"):
        compose_arguments_per_output_route(
            [ROUTE],
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


def test_exact_calendar_create__materializes_arguments__without_llm() -> None:
    route = {
        "route_id": "calendar-route",
        "resource_type": "CALENDAR_EVENT",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "calendar_create_event",
        "reason_codes": [],
    }
    bound = resolve_default_container(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("calendar_create_event"),
        explicit_container_id="primary",
    )
    objective = {
        "schema_version": 1,
        "route_id": "calendar-route",
        "objective": "Create the requested event",
        "target_semantics": "CALENDAR_EVENT",
        "scope_constraints": [],
        "evidence_refs": ["user-message-1"],
    }
    request_intent = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "RESOURCE", "field": "title", "value": "[GWA OPT] Calendar 42"},
            {"kind": "DATE", "field": "date", "value": "2026-09-08"},
            {"kind": "TIME", "field": "start_time", "value": "15:00"},
            {"kind": "TIME", "field": "end_time", "value": "15:30"},
            {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
        ],
    }

    result = compose_arguments_per_output_route(
        [route],
        objectives=[objective],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        request_intent=request_intent,
        evidence=[
            {
                "evidence_id": "user-message-1",
                "origin_type": "USER_MESSAGE",
                "kind": "USER_REQUEST",
            }
        ],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result == (
        {
            "schema_version": 1,
            "route_id": "calendar-route",
            "arguments": {
                "calendar_id": "primary",
                "payload": {
                    "title": "[GWA OPT] Calendar 42",
                    "start": "2026-09-08T15:00:00+09:00",
                    "end": "2026-09-08T15:30:00+09:00",
                },
            },
            "evidence_refs": ["user-message-1"],
        },
    )


def test_exact_task_create__materializes_arguments__without_llm() -> None:
    bound = resolve_default_container(
        route=ROUTE,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="@default",
    )
    request_intent = {
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "RESOURCE", "field": "title", "value": "Submit report"}
        ],
    }

    result = compose_arguments_per_output_route(
        [ROUTE],
        objectives=[OBJECTIVE],  # type: ignore[list-item]
        bound_tool_schemas=[bound],
        request_intent=request_intent,
        evidence=[{"evidence_ref": "e1"}],
        invoke=lambda *_: (_ for _ in ()).throw(AssertionError("LLM must be skipped")),
    )

    assert result[0]["arguments"] == {
        "task_list_id": "@default",
        "payload": {"title": "Submit report"},
    }
