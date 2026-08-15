"""Bounded Product-Prompt projections for RetrievalQueryPlannerAgent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.workflows.api_acquisition import RetrievalBudget
from google_work_agent.application.workflows.handoff_contracts import RequestIntentV2
from google_work_agent.application.workflows.tool_routing import (
    InputToolRouteV1,
    coarse_resource_category,
)


def initial_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
) -> dict[str, object]:
    """Project exactly the initial-round V2 input contract."""
    return {
        "request_intent": request_intent,
        "input_routes": [_prompt_route(route) for route in input_routes],
        "retrieval_budget": retrieval_budget.as_remaining(),
    }


def followup_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    followup: Mapping[str, object],
) -> dict[str, object]:
    """Add only the bounded follow-up metadata permitted by the V2 contract."""
    result = initial_retrieval_planner_input(
        request_intent=request_intent,
        input_routes=input_routes,
        retrieval_budget=retrieval_budget,
    )
    for field in (
        "current_round_no",
        "prior_query_attempts",
        "unresolved_sufficiency_issues",
        "read_result_summaries",
    ):
        if field not in followup:
            raise ValueError(f"follow-up retrieval planner input is missing {field}")
        result[field] = followup[field]
    return result


def _prompt_route(route: InputToolRouteV1) -> dict[str, object]:
    return {
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": coarse_resource_category(route["resource_type"]),
        "allowed_read_tool_ids": list(route["allowed_read_tool_ids"]),
        "required": route["required"],
        "reason_codes": list(route["reason_codes"]),
    }
