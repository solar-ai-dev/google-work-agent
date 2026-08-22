"""Owner-local LangGraph state for Retrieval."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class RetrievalState(TypedDict):
    """Invocation-local state. Only final_result/workflow_signal are parent-facing patches."""

    operation_inputs: dict[str, dict[str, object]]
    query_plan: NotRequired[object]
    fetch_plan: NotRequired[object]
    read_result: NotRequired[object]
    segments: NotRequired[object]
    ranked_segments: NotRequired[object]
    evidence_selection: NotRequired[object]
    sufficiency: NotRequired[object]
    final_result: NotRequired[object]
    workflow_signal: NotRequired[object]
