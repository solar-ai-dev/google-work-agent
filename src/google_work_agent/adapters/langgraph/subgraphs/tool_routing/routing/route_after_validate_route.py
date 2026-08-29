from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_validate_route(state: ToolRouteStateV1) -> Literal["end"]:
    if "tool_route_plan" not in state:
        raise ValueError("tool-routing validated route projection is required")
    return "end"
