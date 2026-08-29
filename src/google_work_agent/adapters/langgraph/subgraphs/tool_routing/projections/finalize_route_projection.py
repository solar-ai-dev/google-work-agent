from __future__ import annotations

from typing import TypedDict

from google_work_agent.adapters.langgraph.main.state import _require_state_value
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    RouteBindingCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


class FinalizeRouteInput(TypedDict):
    request_intent: RequestIntentV2
    binding: RouteBindingCandidateV1
    selected_tools: dict[tuple[str, str], str]
    previous_plan: ToolRoutePlanV2 | None


def project_finalize_route_input(state: ToolRouteStateV1) -> FinalizeRouteInput:
    candidate = state.get("io_resource_candidate")
    registry_candidates = state.get("registry_candidates")
    input_routes = state.get("bound_input_routes")
    output_routes = state.get("bound_output_routes")
    if candidate is None or registry_candidates is None or input_routes is None:
        raise ValueError("tool-routing Registry binding is required")
    binding = RouteBindingCandidateV1(
        semantic=candidate,
        input_routes=tuple(input_routes),
        output_candidates=tuple(registry_candidates),
    )
    return {
        "request_intent": _require_state_value(state.get("request_intent"), "request_intent"),
        "binding": binding,
        "selected_tools": {
            (route["resource_type"], route["effect"]): route["selected_tool_id"]
            for route in output_routes or []
        },
        "previous_plan": state.get("tool_route_plan"),
    }
