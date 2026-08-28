from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import _require_state_value, request_from_state
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def project_determine_io_resources_input(state: ToolRouteStateV1) -> dict[str, object]:
    return {
        "request_intent": _require_state_value(state.get("request_intent"), "request_intent"),
        "request": request_from_state(state),
        "retry_budget": state["retry_budget"],
        "confirmation_response": state.get("tr_confirmation_response"),
    }
