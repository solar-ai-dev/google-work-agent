from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_select_tool_if_needed(
    state: ToolRouteStateV1,
) -> Literal["finalize_route"]:
    if "bound_output_routes" not in state:
        raise ValueError("tool-routing selected tools are required")
    return "finalize_route"
