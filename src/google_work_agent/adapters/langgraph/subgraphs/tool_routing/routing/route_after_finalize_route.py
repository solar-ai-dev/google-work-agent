from __future__ import annotations

from typing import Literal
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def route_after_finalize_route(state: ToolRoutingState) -> Literal["confirm", "validate_route"]:
    result = state.get("tr_result")
    if result is None:
        raise ValueError("tool-routing result is required")
    if result["disposition"] == "NEEDS_CONFIRMATION":
        return "confirm"
    return "validate_route"
