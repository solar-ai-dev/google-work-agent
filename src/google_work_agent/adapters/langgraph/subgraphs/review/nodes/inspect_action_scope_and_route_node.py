"""Thin LangGraph adapter for review.inspect_action_scope_and_route."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import project_review_input

def inspect_action_scope_and_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_review_input(state)
    return {"action_scope_route_findings": operation(projected)}
