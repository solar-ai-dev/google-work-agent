"""Thin adapter for review.inspect_constraints_and_policy_summary."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_constraints_and_policy_summary_projection as input_projection,
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
    projected = input_projection.project_inspect_constraints_and_policy_summary_input(state)
    return {
        "constraints_policy_result": inspect_constraints_and_policy_summary(
            request_intent=projected["request_intent"],
            planning_result=projected["planning_result"],
            policy_summary=projected["policy_summary"],
            work_analysis=projected.get("work_analysis"),
            evidence=projected.get("evidence", ()),
            confirmation_response=projected.get("confirmation_response"),
            invoke=invoke,
        )
    }
