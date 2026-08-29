from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def project_select_tool_if_needed_input(
    state: ToolRouteStateV1,
) -> dict[str, object]:
    candidates = state.get("registry_candidates")
    if candidates is None:
        raise ValueError("tool-routing Registry binding is required before selection")
    return {
        "registry_candidates": candidates,
        "confirmation_response": None,
    }
