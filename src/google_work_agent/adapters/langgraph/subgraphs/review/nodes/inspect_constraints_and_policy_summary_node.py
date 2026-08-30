# ruff: noqa: E501
"""Thin adapter for review.inspect_constraints_and_policy_summary."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_constraints_and_policy_summary_projection import (
    project_inspect_constraints_and_policy_summary_input,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)


def inspect_constraints_and_policy_summary_node(
    state: Mapping[str, object], *, invoke: ReviewSemanticInvoker
) -> dict[str, object]:
    projected = project_inspect_constraints_and_policy_summary_input(state)
    return {
        "constraints_policy_result": inspect_constraints_and_policy_summary(
            request_intent=projected["request_intent"],  # type: ignore[arg-type]
            planning_result=projected["planning_result"],  # type: ignore[arg-type]
            policy_summary=projected["policy_summary"],  # type: ignore[arg-type]
            work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
            evidence=projected.get("evidence", ()),  # type: ignore[arg-type]
            confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
            invoke=invoke,
        )
    }
