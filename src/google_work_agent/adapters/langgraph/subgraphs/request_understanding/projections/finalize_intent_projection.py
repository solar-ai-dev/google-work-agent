from __future__ import annotations

from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)


class FinalizeIntentInput(TypedDict):
    goal_candidate: RequestGoalCandidateV1
    ambiguity_candidate: AmbiguityV1


def project_finalize_intent_input(state: RequestUnderstandingStateV2) -> FinalizeIntentInput:
    """Project only the same-invocation Request Understanding candidates."""
    goal_candidate = state.get("goal_candidate")
    ambiguity_candidate = state.get("ambiguity_candidate")
    if goal_candidate is None or ambiguity_candidate is None:
        raise ValueError("request-understanding candidates are required")
    return {
        "goal_candidate": goal_candidate,
        "ambiguity_candidate": ambiguity_candidate,
    }
