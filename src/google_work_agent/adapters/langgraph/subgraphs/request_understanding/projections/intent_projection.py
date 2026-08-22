from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def project_intent_input(state: RequestUnderstandingState) -> dict[str, object]:
    """Allowlist the finalized owner artifact only."""

    intent = state.get("ru_intent")
    if intent is None:
        raise ValueError("request intent is required")
    return {"intent": intent}
