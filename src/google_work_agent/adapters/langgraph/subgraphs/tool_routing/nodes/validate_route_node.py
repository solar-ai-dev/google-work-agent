from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.validate_route import validate_route
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

from ..projections.validate_route_projection import (
    project_validate_route_input,
)


def validate_route_node(
    state: ToolRouteStateV1, *, tool_catalog: SignedToolRegistry
) -> ToolRouteStateV1:
    plan = project_validate_route_input(state)["final_route"]
    if plan is not None:
        validate_route(plan, tool_catalog=tool_catalog)
    return {"tool_route_plan": plan, "workflow_signal": state.get("workflow_signal")}
