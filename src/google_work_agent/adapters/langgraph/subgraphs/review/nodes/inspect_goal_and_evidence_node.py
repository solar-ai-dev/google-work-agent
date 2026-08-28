"""Thin adapter for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import (
    project_review_input,
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
    projected = project_review_input(state)
    return {
        "goal_evidence_findings": inspect_goal_and_evidence(
            request_intent=_mapping(projected, "request_intent"),
            tool_route_plan=_mapping(projected, "tool_route_plan"),
            planning_result=_mapping(projected, "planning_result"),
            work_analysis=_optional_mapping(projected.get("work_analysis")),
            evidence=_sequence(projected.get("evidence", ())),
            policy_summary=_optional_mapping(projected.get("policy_summary")),
            invoke=invoke,
        )
    }


def _mapping(projected: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = projected.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is required")
    return value


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("optional Review input must be an object")
    return value


def _sequence(value: object) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    return value  # type: ignore[return-value]
