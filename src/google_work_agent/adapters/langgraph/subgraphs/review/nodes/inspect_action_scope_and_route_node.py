# ruff: noqa: E501
"""Thin adapter for review.inspect_action_scope_and_route."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_action_scope_and_route_projection import (
    project_inspect_action_scope_and_route_input,
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
    projected = project_inspect_action_scope_and_route_input(state)
    return {
        "action_scope_route_result": inspect_action_scope_and_route(
            request_intent=projected["request_intent"],  # type: ignore[arg-type]
            tool_route_plan=projected["tool_route_plan"],  # type: ignore[arg-type]
            planning_result=projected["planning_result"],  # type: ignore[arg-type]
            work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
            evidence=projected["evidence"],  # type: ignore[arg-type]
            confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
            invoke=invoke,
        )
    }
