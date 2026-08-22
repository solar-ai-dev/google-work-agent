from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def project_semantic_candidate_input(state: ToolRoutingState) -> dict[str, object]:
    candidate = state.get("tr_semantic_candidate")
    if candidate is None:
        raise ValueError("tool-routing semantic candidate is required")
    return {"candidate": candidate}
