"""Thin adapter for deterministic review.validate_review."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import (
    project_review_input,
)
from google_work_agent.application.agents.review.validate_review import validate_review


def validate_review_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_review_input(state)
    candidate = projected.get("aggregated_findings")
    if candidate is None:
        raise ValueError("aggregated Review result is required")
    return {"review_result": validate_review(candidate)}
