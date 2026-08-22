"""Review owner-local LangGraph state."""

from __future__ import annotations

from typing import TypedDict


class ReviewState(TypedDict, total=False):
    request_intent: object
    tool_route_plan: object
    retrieval_result: object
    work_analysis: object
    planning_result: object
    evidence: object
    policy_summary: object
    goal_evidence_findings: object
    action_scope_route_findings: object
    constraints_policy_findings: object
    aggregated_findings: object
    review_result: object
    affected_dimension_recheck: object
    workflow_signal: object
