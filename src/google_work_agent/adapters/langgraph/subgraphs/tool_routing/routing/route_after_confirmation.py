from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def route_after_confirmation(
    state: ToolRoutingState,
) -> Literal["determine_io_resources", "finalize_route", "validate_route"]:
    origin = state.get("tr_confirmation_origin")
    result = state.get("tr_result")
    if result is not None and result["disposition"] == "BLOCKED":
        return "validate_route"
    if origin == "scope_expansion":
        return "finalize_route"
    return "determine_io_resources"
