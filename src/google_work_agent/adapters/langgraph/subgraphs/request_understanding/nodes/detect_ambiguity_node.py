from __future__ import annotations

from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.candidate_projection import (
    project_candidate_input,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def detect_ambiguity_node(state: RequestUnderstandingState) -> RequestUnderstandingState:
    projection = project_candidate_input(state)
    return {"ru_ambiguity": detect_ambiguity(projection["candidate"])}
