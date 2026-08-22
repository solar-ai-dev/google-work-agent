"""Thin adapter for deterministic review.validate_review."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import (
    project_review_input,
)
from google_work_agent.application.agents.review.validate_review import validate_review
from google_work_agent.application.orchestration.handoff_contracts import (
    PlanningRevisionIssueV1,
    PlanningRevisionRequiredV1,
)

_REVIEW_DIMENSIONS = {"GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"}


def validate_review_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_review_input(state)
    candidate = projected.get("aggregated_findings")
    if candidate is None:
        raise ValueError("aggregated Review result is required")
    review_result = validate_review(candidate)
    if review_result["status"] != "REVISE":
        return {"review_result": review_result, "workflow_signal": None}
    return {
        "review_result": review_result,
        "workflow_signal": _planning_revision_signal(review_result),
    }


def _planning_revision_signal(review_result: Mapping[str, object]) -> PlanningRevisionRequiredV1:
    raw_issues = review_result.get("issues")
    if not isinstance(raw_issues, list) or not raw_issues:
        raise ValueError("REVISE requires bounded revision issues")
    issues: list[PlanningRevisionIssueV1] = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, Mapping):
            raise ValueError("REVISE issue must be an object")
        dimension = raw_issue.get("dimension")
        code = raw_issue.get("code")
        description = raw_issue.get("description")
        action_id = raw_issue.get("action_id")
        route_id = raw_issue.get("route_id")
        if dimension not in _REVIEW_DIMENSIONS:
            raise ValueError("REVISE issue dimension is required")
        if not isinstance(code, str) or not code or not isinstance(description, str):
            raise ValueError("REVISE issue code/description are required")
        if action_id is not None and not isinstance(action_id, str):
            raise ValueError("REVISE issue action_id must be a string or null")
        if route_id is not None and not isinstance(route_id, str):
            raise ValueError("REVISE issue route_id must be a string or null")
        issues.append(
            {
                "dimension": dimension,  # type: ignore[typeddict-item]
                "code": code,
                "description": description,
                "action_id": action_id,
                "route_id": route_id,
            }
        )
    return {
        "kind": "PLANNING_REVISION_REQUIRED",
        "destination": "PLANNING",
        "disposition": "REVISE",
        "issues": issues,
    }
