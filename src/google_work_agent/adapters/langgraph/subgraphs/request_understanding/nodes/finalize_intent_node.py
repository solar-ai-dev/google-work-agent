from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.candidate_projection import (
    project_candidate_input,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def finalize_intent_node(
    state: RequestUnderstandingState,
    *,
    id_factory: Callable[[], str],
) -> RequestUnderstandingState:
    projection = project_candidate_input(state)
    intent = finalize_intent(projection["candidate"], artifact_id=id_factory())
    return {"ru_intent": intent}
