"""Bounded Product-Prompt projections for canonical retrieval.plan_query."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    max_sources: int = 3
    max_pages_per_source: int = 1
    max_page_size: int = 20
    max_candidates_per_source: int = 20
    max_details_per_source: int = 10

    def as_remaining(self) -> dict[str, int]:
        return {
            "sources": self.max_sources,
            "pages": self.max_sources * self.max_pages_per_source,
            "candidates": self.max_sources * self.max_candidates_per_source,
            "details": self.max_sources * self.max_details_per_source,
        }


DEFAULT_RETRIEVAL_BUDGET = RetrievalBudget()


def initial_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Project exactly the initial-round V2 input contract."""
    return {
        "request_intent": request_intent,
        "input_routes": [
            _prompt_route(
                route,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
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
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Add only the bounded follow-up metadata permitted by the V2 contract."""
    result = initial_retrieval_planner_input(
        request_intent=request_intent,
        input_routes=input_routes,
        retrieval_budget=retrieval_budget,
        validated_resource_refs=validated_resource_refs,
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
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
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
    resource_refs = (validated_resource_refs or {}).get(route["route_id"])
    if resource_refs:
        prompt_route["resource_refs"] = list(resource_refs)
    container_refs = (validated_container_refs or {}).get(route["route_id"])
    if container_refs:
        # Pre-Prompt Runtime Closure: the only container refs the LLM is
        # ever shown are already-validated internal refs resolved by
        # deterministic code (see _validated_task_container_refs,
        # context_retrieval.py) -- never a raw provider/task_list_id the
        # model could invent on its own.
        prompt_route["container_refs"] = list(container_refs)
    return prompt_route
