from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)


def route_after_finalize_intent(
    state: RequestUnderstandingStateV2,
) -> Literal["identify_goal", "end"]:
    if state.get("__target__") == "end" and state.get("execution_summary") is not None:
        return "end"
    if state.get("request_intent") is not None and state.get("final_intent") is not None:
        return "end"
    ambiguity = state.get("ambiguity_candidate")
    prompt_context = state.get("prompt_context", {})
    if (
        ambiguity is not None
        and ambiguity["requires_confirmation"]
        and isinstance(prompt_context, Mapping)
        and isinstance(prompt_context.get("confirmation_response"), Mapping)
    ):
        return "identify_goal"
    raise ValueError("validated request intent or confirmation response is required")
