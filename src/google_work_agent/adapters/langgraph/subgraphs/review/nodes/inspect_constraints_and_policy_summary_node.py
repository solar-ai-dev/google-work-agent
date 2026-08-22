"""Thin LangGraph adapter for review.inspect_constraints_and_policy_summary."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import project_review_input

def inspect_constraints_and_policy_summary_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_review_input(state)
    return {"constraints_policy_findings": operation(projected)}
