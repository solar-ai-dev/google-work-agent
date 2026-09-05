"""Recognize fully acquired Task duplicate and Calendar conflict policy inputs."""

from collections.abc import Mapping

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.ports.system.contracts.confirmation import ConfirmationResponseProjectionV1


def is_complete_create_policy_read(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> bool:
    """Accept completed policy acquisition, not creation or duplicate clearance."""

    if (
        confirmation_response is not None
        or tool_route_plan is None
        or request_intent["analysis_requirement"] != "NONE"
        or set(request_intent["requested_effect_hints"]) != {"CREATE"}

        or acquisition_result["status"] != "COMPLETE"
        or acquisition_result["missing_slots"]
    ):
        return False
    output_routes = tool_route_plan["output_plan"].get("output_routes")
    if (
        tool_route_plan["output_plan"]["output_mode"] != "ACTION"
        or not isinstance(output_routes, list)
        or len(output_routes) != 1
        or not isinstance(output_routes[0], Mapping)
        or output_routes[0].get("effect") != "CREATE"

    ):
        return False
    resource = output_routes[0].get("resource_type")
    if resource == "TASK":
        required_resources = {"TASK", "TASK_LIST"}
        reason_code = "POLICY_TASK_DUPLICATE_CHECK"
    elif resource == "CALENDAR_EVENT":
        required_resources = {"CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
        reason_code = "POLICY_CALENDAR_CONFLICT_CHECK"
    else:
        return False
    if set(request_intent["requested_resource_hints"]) != {resource}:
        return False
    input_routes = tool_route_plan["input_plan"]["input_routes"]
    if {route["resource_type"] for route in input_routes} != required_resources:
        return False
    if any(
        not route["required"]
        or route["reason_codes"] != [reason_code]
        for route in input_routes
    ):
        return False
    summaries_by_route = {
        summary.get("route_id"): summary
        for summary in acquisition_result["source_summaries"]
        if isinstance(summary.get("route_id"), str)
    }
    return all(
        route["route_id"] in summaries_by_route
        and summaries_by_route[route["route_id"]].get("status") == "COMPLETE"
        for route in input_routes
    )

