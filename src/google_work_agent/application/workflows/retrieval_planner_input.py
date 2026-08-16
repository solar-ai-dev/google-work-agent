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
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Project exactly the initial-round V2 input contract."""
    return {
        "request_intent": request_intent,
        "input_routes": [
            _prompt_route(route, validated_container_refs=validated_container_refs)
            for route in input_routes
        ],
        "retrieval_budget": retrieval_budget.as_remaining(),
    }


def followup_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    followup: Mapping[str, object],
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Add only the bounded follow-up metadata permitted by the V2 contract."""
    result = initial_retrieval_planner_input(
        request_intent=request_intent,
        input_routes=input_routes,
        retrieval_budget=retrieval_budget,
        validated_container_refs=validated_container_refs,
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


def _prompt_route(
    route: InputToolRouteV1,
    *,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    prompt_route: dict[str, object] = {
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": coarse_resource_category(route["resource_type"]),
        "allowed_read_tool_ids": list(route["allowed_read_tool_ids"]),
        "required": route["required"],
        "reason_codes": list(route["reason_codes"]),
    }
    container_refs = (validated_container_refs or {}).get(route["route_id"])
    if container_refs:
        # Pre-Prompt Runtime Closure: the only container refs the LLM is
        # ever shown are already-validated internal refs resolved by
        # deterministic code (see _validated_task_container_refs,
        # context_retrieval.py) -- never a raw provider/task_list_id the
        # model could invent on its own.
        prompt_route["container_refs"] = list(container_refs)
    return prompt_route
