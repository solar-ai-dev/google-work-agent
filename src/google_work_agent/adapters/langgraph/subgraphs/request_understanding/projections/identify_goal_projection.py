from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class IdentifyGoalInput(TypedDict):
    request: WorkflowStartRequest
    confirmation_response: NotRequired[ConfirmationResponseProjectionV1]


def project_identify_goal_input(state: RequestUnderstandingStateV2) -> IdentifyGoalInput:
    """Project only current-Run fields allowed by the identify-goal prompt contract."""
    request = request_from_state(state)
    projected: IdentifyGoalInput = {"request": request}
    prompt_context = state.get("prompt_context", {})
    confirmation = prompt_context.get("confirmation_response")
    if confirmation is not None:
        projected["confirmation_response"] = validate_confirmation_response_projection_v1(
            confirmation
        )
    return projected
