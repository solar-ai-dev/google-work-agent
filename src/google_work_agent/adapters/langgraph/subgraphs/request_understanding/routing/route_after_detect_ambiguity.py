from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)


def route_after_detect_ambiguity(
    state: RequestUnderstandingStateV2,
) -> Literal["confirm", "finalize_intent"]:
    ambiguity = state.get("ru_ambiguity")
    if ambiguity is None:
        raise ValueError("request-understanding ambiguity result is required")
    return "confirm" if ambiguity["requires_confirmation"] else "finalize_intent"
