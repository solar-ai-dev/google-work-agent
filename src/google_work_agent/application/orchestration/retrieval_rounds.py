"""Deterministic Retrieval-round continuity across subgraph invocations."""

from __future__ import annotations

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import RetrievalResultV1

MAX_RETRIEVAL_ROUNDS = 3


class RetrievalRoundLimitExceeded(ValueError):
    """A same-route additional Retrieval would exceed the canonical limit."""


def initialize_current_round_no(
    *,
    prior_result: RetrievalResultV1 | None,
    tool_route_plan: ToolRoutePlanV2,
) -> int:
    """Project the next 0-based local round from the official prior handoff."""
    if prior_result is None or not _uses_current_input_route(prior_result, tool_route_plan):
        return 0
    completed_rounds = prior_result["retrieval_rounds"]
    if completed_rounds >= MAX_RETRIEVAL_ROUNDS:
        raise RetrievalRoundLimitExceeded("same-route retrieval round limit is exhausted")
    return completed_rounds


def retrieval_round_count(*, current_round_no: int) -> int:
    if current_round_no < 0 or current_round_no >= MAX_RETRIEVAL_ROUNDS:
        raise ValueError("current_round_no is outside the canonical retrieval round range")
    return current_round_no + 1


def _uses_current_input_route(
    result: RetrievalResultV1,
    tool_route_plan: ToolRoutePlanV2,
) -> bool:
    input_meta = tool_route_plan["input_plan"]["meta"]
    return {
        "artifact_id": input_meta["artifact_id"],
        "revision": input_meta["revision"],
    } in result["meta"]["based_on"]
