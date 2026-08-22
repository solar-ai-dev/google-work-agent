from __future__ import annotations

from google_work_agent.application.agents.request_understanding.validate_intent import validate_intent
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.intent_projection import project_intent_input
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import RequestUnderstandingState


def validate_intent_node(state: RequestUnderstandingState) -> RequestUnderstandingState:
    projection = project_intent_input(state)
    intent = validate_intent(projection["intent"], require_meta=True)
    return {"request_intent": intent}
