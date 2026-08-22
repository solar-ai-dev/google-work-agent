from __future__ import annotations

from typing import Literal
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def route_after_determine_io_resources(state: ToolRoutingState) -> Literal["confirm", "select_tool_if_needed"]:
    result = state.get("tr_result")
    if result is not None and result["disposition"] == "NEEDS_CONFIRMATION":
        return "confirm"
    if state.get("tr_semantic_candidate") is None:
        raise ValueError("tool-routing semantic candidate is required")
    return "select_tool_if_needed"
