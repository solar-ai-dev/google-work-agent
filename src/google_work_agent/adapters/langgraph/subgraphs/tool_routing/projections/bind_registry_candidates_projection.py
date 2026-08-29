from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.orchestration.contracts import PolicyConfirmationReceiptV1


class BindRegistryCandidatesInput(TypedDict):
    candidate: SemanticRouteCandidate
    request_intent: RequestIntentV2
    policy_confirmation_receipts: tuple[PolicyConfirmationReceiptV1, ...]
    current_interrupt_id: str | None


def project_bind_registry_candidates_input(
    state: ToolRouteStateV1,
) -> BindRegistryCandidatesInput:
    candidate = state.get("io_resource_candidate")
    if candidate is None:
        raise ValueError("tool-routing semantic candidate is required")
    request_intent = state.get("request_intent")
    if request_intent is None:
        raise ValueError("tool-routing request intent is required")
    prompt_context = state.get("prompt_context", {})
    confirmation_interrupt = (
        prompt_context.get("confirmation_interrupt")
        if isinstance(prompt_context, Mapping)
        else None
    )
    interrupt_id = (
        confirmation_interrupt.get("interrupt_id")
        if isinstance(confirmation_interrupt, Mapping)
        else None
    )
    return {
        "candidate": candidate,
        "request_intent": request_intent,
        "policy_confirmation_receipts": tuple(state.get("policy_confirmation_receipts", [])),
        "current_interrupt_id": interrupt_id if isinstance(interrupt_id, str) else None,
    }
