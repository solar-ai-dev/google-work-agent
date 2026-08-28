from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_determine_io_resources(
    state: ToolRouteStateV1,
) -> Literal["confirm", "bind_registry_candidates"]:
    result = state.get("tr_result")
    if result is not None:
        if result["disposition"] == "NEEDS_CONFIRMATION":
            return "confirm"
        raise ValueError(f"unexpected determine disposition: {result['disposition']}")
    if state.get("tr_semantic_candidate") is None:
        raise ValueError("tool-routing semantic candidate is required")
    return "bind_registry_candidates"
