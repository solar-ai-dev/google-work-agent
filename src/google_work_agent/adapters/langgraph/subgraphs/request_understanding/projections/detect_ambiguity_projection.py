from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class DetectAmbiguityInput(TypedDict):
    request: WorkflowStartRequest
    goal_candidate: RequestGoalCandidateV1
    confirmation_response: NotRequired[ConfirmationResponseProjectionV1]


def project_detect_ambiguity_input(state: RequestUnderstandingStateV2) -> DetectAmbiguityInput:
    """Project the current request and same-invocation goal candidate only."""
    candidate = state.get("goal_candidate")
    if candidate is None:
        raise ValueError("request-understanding goal candidate is required")
    projected: DetectAmbiguityInput = {
        "request": request_from_state(state),
        "goal_candidate": candidate,
    }
    prompt_context = state.get("prompt_context", {})
    confirmation = prompt_context.get("confirmation_response")
    if confirmation is not None:
        projected["confirmation_response"] = validate_confirmation_response_projection_v1(
            confirmation
        )
    return projected
