"""Planning owner-local LangGraph state."""

from __future__ import annotations

from typing import TypedDict


class PlanningState(TypedDict, total=False):
    user_request: str
    request_intent: object
    tool_route_plan: object
    retrieval_result: object
    work_analysis_result: object
    work_analysis: object
    evidence: object
    evidence_refs: object
    confirmation_response: object
    plan_artifact_id: str
    plan_revision: int
    plan_based_on: object
    action_ids_by_route: object
    planning_disposition: str
    answer_outline: object
    answer_draft: object
    final_result: object
    action_objectives: object
    argument_candidates: object
    action_seeds: object
    dependencies: object
    plan_draft: object
    validated_plan: object
    workflow_signal: object
    run_id: str
    retry_budget: object
    trace_context: object
    prompt_context: object
    __request__: object
    __target__: str
    __logical_target__: str
    workflow_phase: str
    planning_result: object
    user_interrupt: object
    finalize_intent: object
    __planning_agent_local__: object
    planning_confirmation: object
    __planning_retry_outline__: bool
