from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_confirmation(
    state: ToolRouteStateV1,
) -> Literal["determine_io_resources", "bind_registry_candidates", "validate_route"]:
    origin = state.get("tr_confirmation_origin")
    result = state.get("tr_result")
    if result is not None and result["disposition"] == "BLOCKED":
        return "validate_route"
    if origin == "scope_expansion":
        return "bind_registry_candidates"
    if origin == "semantic":
        return "determine_io_resources"
    raise ValueError(f"unknown tool-routing confirmation origin: {origin}")
