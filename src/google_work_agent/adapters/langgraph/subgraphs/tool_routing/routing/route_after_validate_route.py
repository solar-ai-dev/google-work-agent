from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_validate_route(state: ToolRouteStateV1) -> Literal["end"]:
    if state.get("tr_result") is None:
        raise ValueError("tool-routing validated result is required")
    if state["tr_result"]["disposition"] not in {
        "ROUTE_READY",
        "NO_TOOL_NEEDED",
        "BLOCKED",
    }:
        raise ValueError(f"unexpected validated disposition: {state['tr_result']['disposition']}")
    return "end"
