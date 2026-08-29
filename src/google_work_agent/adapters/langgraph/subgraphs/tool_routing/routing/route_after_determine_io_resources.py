from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_determine_io_resources(
    state: ToolRouteStateV1,
) -> Literal["finalize_route", "bind_registry_candidates"]:
    if state.get("io_resource_candidate") is None:
        return "finalize_route"
    return "bind_registry_candidates"
