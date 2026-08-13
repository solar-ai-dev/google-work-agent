from copy import deepcopy

import pytest

from google_work_agent.application.workflows.api_acquisition import (
    SourcePlanningValidationError,
    validate_source_fetch_plans_for_route,
)
from google_work_agent.application.workflows.handoff_contracts import RequestIntentV2
from google_work_agent.application.workflows.tool_routing import (
    ToolRouteCoordinator,
    ToolRouteValidationError,
    allowed_input_sources,
    output_routes,
    validate_tool_route_plan_v2,
)
from google_work_agent.domain import ConnectorToolCatalog, build_p0_tool_registry


def _catalog() -> ConnectorToolCatalog:
    catalog = ConnectorToolCatalog()
    catalog.register(connector_id="google_workspace", registry=build_p0_tool_registry())
    return catalog


def _intent(*, resource: str, effect: str) -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": [effect],  # type: ignore[list-item]
        "requested_resource_hints": [resource],
        "analysis_requirement": "REQUIRED",
    }


def _coordinator() -> ToolRouteCoordinator:
    sequence = iter(f"route-{index}" for index in range(30))
    return ToolRouteCoordinator(tool_catalog=_catalog(), id_factory=lambda: next(sequence))


def test_task_create_binds_output_and_duplicate_check_reads() -> None:
    result = _coordinator().route(request_intent=_intent(resource="TASK", effect="CREATE"))

    assert result["disposition"] == "ROUTE_READY"
    plan = result["tool_route_plan"]
    assert plan is not None
    assert output_routes(plan)[0]["selected_tool_id"] == "tasks_create_task"
    assert allowed_input_sources(plan) == {"TASKS"}
    resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
    assert resources == {"TASK", "TASK_LIST"}


def test_calendar_create_adds_event_calendar_and_freebusy_reads() -> None:
    result = _coordinator().route(
        request_intent=_intent(resource="CALENDAR_EVENT", effect="CREATE")
    )

    plan = result["tool_route_plan"]
    assert plan is not None
    resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
    assert resources == {"CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
    assert output_routes(plan)[0]["selected_tool_id"] == "calendar_create_event"


def test_answer_route_freezes_read_dependencies_and_revision() -> None:
    coordinator = _coordinator()
    first = coordinator.route(
        request_intent=_intent(resource="GMAIL_THREAD", effect="READ")
    )
    first_plan = first["tool_route_plan"]
    assert first_plan is not None
    resources = {
        route["resource_type"] for route in first_plan["input_plan"]["input_routes"]
    }
    assert resources == {"GMAIL_THREAD", "GMAIL_MESSAGE"}

    second = coordinator.route(
        request_intent=_intent(resource="GMAIL_THREAD", effect="READ"),
        previous_plan=first_plan,
    )
    second_plan = second["tool_route_plan"]
    assert second_plan is not None
    assert second_plan["input_plan"]["meta"]["revision"] == 2
    assert first_plan["input_plan"]["meta"]["revision"] == 1


def test_validator_rejects_unregistered_or_mismatched_output_tool() -> None:
    result = _coordinator().route(request_intent=_intent(resource="TASK", effect="CREATE"))
    plan = result["tool_route_plan"]
    assert plan is not None
    invalid = deepcopy(plan)
    assert invalid["output_plan"]["output_mode"] == "ACTION"
    invalid["output_plan"]["output_routes"][0]["selected_tool_id"] = "gmail_send"

    with pytest.raises(ToolRouteValidationError, match="binding is invalid"):
        validate_tool_route_plan_v2(invalid, tool_catalog=_catalog())


def test_validator_rejects_unknown_schema_version() -> None:
    result = _coordinator().route(request_intent=_intent(resource="TASK", effect="CREATE"))
    plan = result["tool_route_plan"]
    assert plan is not None
    invalid = deepcopy(plan)
    invalid["schema_version"] = 3  # type: ignore[typeddict-item]

    with pytest.raises(ToolRouteValidationError, match="schema_version"):
        validate_tool_route_plan_v2(invalid, tool_catalog=_catalog())


def test_source_planning_cannot_escape_frozen_input_route() -> None:
    result = _coordinator().route(
        request_intent=_intent(resource="TASK", effect="READ")
    )
    plan = result["tool_route_plan"]
    assert plan is not None
    calendar_plan = {
        "schema_version": 2,
        "source": "CALENDAR",
        "priority": 1,
        "reason_codes": ["SOURCE_REQUIRED"],
        "constraints": {},
        "page_size": 10,
        "max_pages": 1,
        "max_candidates": 10,
        "detail_limit": 5,
        "required": True,
        "calendar_read_mode": "EVENTS_ONLY",
        "temporal_query": None,
    }

    with pytest.raises(SourcePlanningValidationError, match="outside frozen input route"):
        validate_source_fetch_plans_for_route([calendar_plan], tool_route_plan=plan)
