from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.result_projection import (
    project_result_input,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState
from google_work_agent.application.agents.tool_routing.validate_route import validate_route
from google_work_agent.domain.tool_registry import ConnectorToolCatalog


def validate_route_node(
    state: ToolRoutingState, *, tool_catalog: ConnectorToolCatalog
) -> ToolRoutingState:
    result = project_result_input(state)["result"]
    plan = result.get("tool_route_plan")
    if plan is not None:
        validate_route(plan, tool_catalog=tool_catalog)
    return {"tool_route_plan": plan, "workflow_signal": result.get("workflow_signal")}
