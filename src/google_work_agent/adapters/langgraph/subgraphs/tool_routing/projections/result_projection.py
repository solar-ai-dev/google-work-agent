from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def project_result_input(state: ToolRoutingState) -> dict[str, object]:
    result = state.get("tr_result")
    if result is None:
        raise ValueError("tool-routing result is required")
    return {"result": result}
