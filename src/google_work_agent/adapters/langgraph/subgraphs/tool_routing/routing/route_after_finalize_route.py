from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1


def route_after_finalize_route(
    state: ToolRouteStateV1,
) -> Literal["determine_io_resources", "bind_registry_candidates", "validate_route"]:
    if state.get("final_route") is not None:
        return "validate_route"
    prompt_context = state.get("prompt_context", {})
    confirmation = (
        prompt_context.get("confirmation_interrupt")
        if isinstance(prompt_context, Mapping)
        else None
    )
    if isinstance(confirmation, Mapping):
        origin = confirmation.get("origin")
        if origin == "semantic":
            return "determine_io_resources"
        if origin == "scope_expansion":
            interrupt_id = confirmation.get("interrupt_id")
            for receipt in reversed(state.get("policy_confirmation_receipts", [])):
                if receipt["interrupt_id"] != interrupt_id:
                    continue
                return (
                    "bind_registry_candidates"
                    if receipt["decision"] == "APPROVED"
                    else "validate_route"
                )
    if state.get("workflow_signal") is not None:
        return "bind_registry_candidates"
    return "validate_route"
