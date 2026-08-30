"""Review owner-local LangGraph state."""

from __future__ import annotations

from typing import TypedDict

from google_work_agent.application.orchestration.handoff_contracts import WorkflowSignalV1


class ReviewState(TypedDict, total=False):
    request_intent: object
    tool_route_plan: object
    retrieval_result: object
    work_analysis: object
    planning_result: object
    evidence: object
    policy_summary: object
    review_phase: str
    review_artifact_id: str
    review_revision: int
    review_based_on: object
    prior_review_findings: object
    affected_dimensions: object
    affected_action_ids: object
    affected_route_ids: object
    goal_evidence_result: object
    action_scope_route_result: object
    constraints_policy_result: object
    affected_dimension_recheck: object
    review_result: object
    plan_review: object
    workflow_signal: WorkflowSignalV1 | None
