from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRouteResultV1,
)


def project_validate_route_input(state: ToolRouteStateV1) -> dict[str, ToolRouteResultV1]:
    result = state.get("tr_result")
    if result is None:
        raise ValueError("tool-routing result is required")
    return {"result": result}
