from __future__ import annotations

from google_work_agent.adapters.langgraph.graph_state import _require_state_value
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def project_binding_input(state: ToolRoutingState) -> dict[str, object]:
    binding = state.get("tr_binding")
    if binding is None:
        raise ValueError("tool-routing Registry binding is required")
    return {
        "request_intent": _require_state_value(state.get("request_intent"), "request_intent"),
        "binding": binding,
        "selected_tools": dict(state.get("tr_selected_tools", {})),
        "previous_plan": state.get("tool_route_plan"),
        "policy_confirmation_receipts": tuple(state.get("policy_confirmation_receipts", [])),
    }
