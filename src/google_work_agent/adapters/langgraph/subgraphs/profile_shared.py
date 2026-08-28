"""Helpers shared by the THREE_STAGE and SINGLE_BASELINE candidate profiles.

THREE_STAGE and SINGLE_BASELINE are E06-A architecture candidates under
comparison, not features shipped alongside the default SIX_ROLE_BASELINE
profile (see the comment on graph profile selection in ``runtime.py``).
Moved out of the monolithic ``adapters.langgraph.runtime`` (Stage 6 of the
LangGraph module cleanup) with no behavior change.
"""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.orchestration.contracts import GraphStateUpdateV1
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    RequestIntentV2,
    RetrievalResultV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.profile_fused import (
    ProfilePlanningProjectionV1,
    ProfileReasonPlanOutputV1,
)
from google_work_agent.application.orchestration.retrieval_finalize import (
    finalize_retrieval_result,
)
from google_work_agent.application.orchestration.solution_planning import (
    SolutionPlanningAgent,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.orchestration.tool_routing import (
    ToolRouteCoordinator,
    ToolRoutePlanV2,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class ProfileToolRouteError(ValueError):
    """Raised when a comparison profile cannot freeze its canonical route."""


def build_profile_tool_route_plan(
    request_intent: object,
    *,
    id_factory: Callable[[], str],
    coordinator: ToolRouteCoordinator,
) -> tuple[RequestIntentV2, ToolRoutePlanV2]:
    """Materialize profile intent identity and freeze the shared Tool Route contract."""

    if not isinstance(request_intent, dict):
        raise ProfileToolRouteError("profile request intent must be an object")
    candidate = validate_intent(request_intent)
    goal_candidate = {
        "goal": candidate["goal"],
        "completion_conditions": candidate["completion_conditions"],
        "constraints": candidate["constraints"],
        "requested_effect_hints": candidate["requested_effect_hints"],
        "requested_resource_hints": candidate["requested_resource_hints"],
        "analysis_requirement": candidate["analysis_requirement"],
    }
    materialized = finalize_intent(
        goal_candidate,
        candidate["ambiguity"],
        artifact_id=id_factory(),
    )
    result = coordinator.route(request_intent=materialized)
    plan = result["tool_route_plan"]
    if plan is None:
        reasons = ", ".join(result["reason_codes"]) or result["disposition"]
        raise ProfileToolRouteError(f"profile tool route is not ready: {reasons}")
    return materialized, plan


def build_profile_retrieval_result(
    context_result: ContextRetrievalResultV1,
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    artifact_id: str,
) -> tuple[RetrievalResultV1, list[EvidenceDraftV1]]:
    """Project fused-profile context onto the canonical Retrieval handoff."""

    selected_segment_ids = list(context_result["selected_segment_ids"])
    selected = set(selected_segment_ids)
    evidence_drafts = [
        item for item in context_result["evidence_drafts"] if item["segment_id"] in selected
    ]
    result = finalize_retrieval_result(
        artifact_id=artifact_id,
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        selection_result={
            "schema_version": 2,
            "selected_segment_ids": selected_segment_ids,
            "evidence_drafts": [
                {
                    "segment_id": item["segment_id"],
                    "role": "SUPPORTS",
                    "relevance_reason": "selected by fused profile retrieval",
                }
                for item in evidence_drafts
            ],
            "excluded_segment_ids": [],
        },
        evidence_drafts=evidence_drafts,
        sufficiency_result={
            "schema_version": 2,
            "status": context_result["status"],
            "issues": [],
        },
        current_round_no=1,
    )
    return result, evidence_drafts


def profile_request_source_prompt_input(request: WorkflowStartRequest) -> dict[str, object]:
    return {
        "request_text": request.request_text,
        "entry_mode": request.entry_mode,
        "selected_resource_ids": list(request.selected_resource_ids),
    }


def profile_post_read_prompt_input(state: GraphState) -> dict[str, object]:
    request = request_from_state(state)
    return {
        "request_text": request.request_text,
        "request_intent": _require_state_value(state["request_intent"], "request_intent"),
        "acquisition_result": _require_state_value(
            state["acquisition_result"], "acquisition_result"
        ),
    }


def profile_trace_context(
    *,
    request: WorkflowStartRequest,
    llm_call_id: str,
) -> ObservabilityContext:
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=llm_call_id,
    )


def planning_result_from_projection(
    planning_result: ProfilePlanningProjectionV1,
) -> AnswerDraftV1 | ActionPlanDraftV1:
    answer_draft = planning_result["answer_draft"]
    if answer_draft is not None:
        return answer_draft
    plan_draft = planning_result["plan_draft"]
    if plan_draft is not None:
        return plan_draft
    raise ValueError("planning_result must contain answer_draft or plan_draft")


def profile_planning_state_update(
    planning_result: ProfilePlanningProjectionV1,
    *,
    analysis_result: WorkAnalysisResultV1,
    planning_agent: SolutionPlanningAgent,
) -> GraphStateUpdateV1:
    result = planning_result_from_projection(planning_result)
    if "answer" in result:
        answer_result = validate_answer_draft_v1(result, analysis_result=analysis_result)
        return planning_agent.build_answer_state_update(answer_result)
    plan_result = validate_action_plan_draft_v1(result, analysis_result=analysis_result)
    return planning_agent.build_plan_state_update(plan_result)


def profile_reason_plan_state_update(
    output: ProfileReasonPlanOutputV1,
    *,
    planning_agent: SolutionPlanningAgent,
) -> GraphStateUpdateV1:
    planning_result = output["planning_result"]
    return {
        "context_result": output["context_result"],
        "analysis_result": output["analysis_result"],
        **profile_planning_state_update(
            planning_result,
            analysis_result=output["analysis_result"],
            planning_agent=planning_agent,
        ),
    }


def build_no_fetch_acquisition_result() -> AcquisitionResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": [],
        "source_summaries": [],
        "missing_slots": [],
        "remaining_budget": {
            "sources": 0,
            "pages": 0,
            "candidates": 0,
            "details": 0,
        },
    }
