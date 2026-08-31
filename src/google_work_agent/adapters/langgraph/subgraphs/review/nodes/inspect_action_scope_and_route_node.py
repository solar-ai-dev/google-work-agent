"""Thin adapter for review.inspect_action_scope_and_route."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_action_scope_and_route_projection as input_projection,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)


def inspect_action_scope_and_route_node(
    state: Mapping[str, object], *, invoke: ReviewSemanticInvoker
) -> dict[str, object]:
    projected = input_projection.project_inspect_action_scope_and_route_input(state)
    return {
        "action_scope_route_result": inspect_action_scope_and_route(
            request_intent=projected["request_intent"],
            tool_route_plan=projected["tool_route_plan"],
            planning_result=projected["planning_result"],
            work_analysis=projected.get("work_analysis"),
            evidence=projected["evidence"],
            confirmation_response=projected.get("confirmation_response"),
            invoke=invoke,
        )
    }
