from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def project_bind_registry_candidates_input(
    state: ToolRouteStateV1,
) -> dict[str, object]:
    candidate = state.get("tr_semantic_candidate")
    if candidate is None:
        raise ValueError("tool-routing semantic candidate is required")
    request_intent = state.get("request_intent")
    if request_intent is None:
        raise ValueError("tool-routing request intent is required")
    return {
        "candidate": candidate,
        "request_intent": request_intent,
        "policy_confirmation_receipts": tuple(state.get("policy_confirmation_receipts", [])),
    }
