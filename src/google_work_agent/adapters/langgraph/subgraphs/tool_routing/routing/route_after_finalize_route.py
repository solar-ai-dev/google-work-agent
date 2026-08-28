from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_finalize_route(state: ToolRouteStateV1) -> Literal["confirm", "validate_route"]:
    result = state.get("tr_result")
    if result is None:
        raise ValueError("tool-routing result is required")
    if result["disposition"] == "NEEDS_CONFIRMATION":
        return "confirm"
    if result["disposition"] not in {"ROUTE_READY", "NO_TOOL_NEEDED", "BLOCKED"}:
        raise ValueError(f"unexpected final route disposition: {result['disposition']}")
    return "validate_route"
