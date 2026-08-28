from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    RouteBindingCandidateV1,
)


def project_select_tool_if_needed_input(
    state: ToolRouteStateV1,
) -> dict[str, RouteBindingCandidateV1]:
    binding = state.get("tr_binding")
    if binding is None:
        raise ValueError("tool-routing Registry binding is required before selection")
    return {"binding": binding}
