from __future__ import annotations

from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)


def route_after_finalize_intent(state: RequestUnderstandingStateV2) -> Literal["end"]:
    if state.get("request_intent") is None:
        raise ValueError("validated request intent is required")
    return "end"
