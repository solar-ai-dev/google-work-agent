from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.finalize_intent_projection import (  # noqa: E501
    project_finalize_intent_input,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)


def finalize_intent_node(
    state: RequestUnderstandingStateV2,
    *,
    id_factory: Callable[[], str],
) -> RequestUnderstandingStateV2:
    projection = project_finalize_intent_input(state)
    intent = finalize_intent(
        projection["goal_candidate"],
        projection["ambiguity_candidate"],
        artifact_id=id_factory(),
    )
    return {"final_intent": intent, "request_intent": intent}
