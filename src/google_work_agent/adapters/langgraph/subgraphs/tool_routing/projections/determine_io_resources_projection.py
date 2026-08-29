from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from google_work_agent.adapters.langgraph.main.state import _require_state_value, request_from_state
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    RunBudgetV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class DetermineIOResourcesInput(TypedDict):
    request_intent: RequestIntentV2
    request: WorkflowStartRequest
    retry_budget: RunBudgetV1
    confirmation_response: ConfirmationResponseProjectionV1 | None


def project_determine_io_resources_input(state: ToolRouteStateV1) -> DetermineIOResourcesInput:
    prompt_context = state.get("prompt_context", {})
    raw_confirmation = (
        prompt_context.get("confirmation_response") if isinstance(prompt_context, Mapping) else None
    )
    confirmation_response = (
        validate_confirmation_response_projection_v1(raw_confirmation)
        if raw_confirmation is not None
        else None
    )
    return {
        "request_intent": _require_state_value(state.get("request_intent"), "request_intent"),
        "request": request_from_state(state),
        "retry_budget": state["retry_budget"],
        "confirmation_response": confirmation_response,
    }
