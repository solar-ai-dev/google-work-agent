"""Planning owner-local LangGraph state."""

from __future__ import annotations

from typing import TypedDict


class PlanningState(TypedDict, total=False):
    user_request: str
    request_intent: object
    tool_route_plan: object
    retrieval_result: object
    work_analysis: object
    evidence: object
    planning_disposition: str
    answer_outline: object
    answer_draft: object
    action_objectives: object
    argument_candidates: object
    dependencies: object
    plan_draft: object
    validated_plan: object
    workflow_signal: object
