# ruff: noqa: E501
"""Thin adapter for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_goal_and_evidence_projection import (
    project_inspect_goal_and_evidence_input,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)


def inspect_goal_and_evidence_node(
    state: Mapping[str, object], *, invoke: ReviewSemanticInvoker
) -> dict[str, object]:
    projected = project_inspect_goal_and_evidence_input(state)
    return {
        "goal_evidence_result": inspect_goal_and_evidence(
            request_intent=projected["request_intent"],  # type: ignore[arg-type]
            planning_result=projected["planning_result"],  # type: ignore[arg-type]
            work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
            evidence=projected["evidence"],  # type: ignore[arg-type]
            confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
            invoke=invoke,
        )
    }
