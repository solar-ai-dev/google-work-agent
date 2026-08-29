from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_bind_registry_candidates(
    state: ToolRouteStateV1,
) -> Literal["finalize_route", "select_tool_if_needed"]:
    if state.get("workflow_signal") is not None:
        return "finalize_route"
    if "registry_candidates" not in state or "bound_input_routes" not in state:
        raise ValueError("tool-routing Registry binding is required")
    return "select_tool_if_needed"
