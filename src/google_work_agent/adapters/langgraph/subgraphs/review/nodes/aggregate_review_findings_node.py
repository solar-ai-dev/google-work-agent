"""Thin LangGraph adapter for review.aggregate_review_findings."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import project_review_input

def aggregate_review_findings_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_review_input(state)
    return {"aggregated_findings": operation(projected)}
