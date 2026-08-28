from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_bind_registry_candidates(
    state: ToolRouteStateV1,
) -> Literal["confirm", "select_tool_if_needed"]:
    result = state.get("tr_result")
    if result is not None:
        if result["disposition"] == "NEEDS_CONFIRMATION":
            return "confirm"
        raise ValueError(f"unexpected binding disposition: {result['disposition']}")
    if state.get("tr_binding") is None:
        raise ValueError("tool-routing Registry binding is required")
    return "select_tool_if_needed"
