"""Helpers shared by the THREE_STAGE and SINGLE_BASELINE candidate profiles.

THREE_STAGE and SINGLE_BASELINE are E06-A architecture candidates under
comparison, not features shipped alongside the default SIX_ROLE_BASELINE
profile (see the comment on graph profile selection in ``runtime.py``).
Moved out of the monolithic ``adapters.langgraph.runtime`` (Stage 6 of the
LangGraph module cleanup) with no behavior change.
"""

from __future__ import annotations

from google_work_agent.adapters.langgraph.graph_state import (
    GraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.ports.observability_events import ObservabilityContext
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.contracts import GraphStateUpdateV1
from google_work_agent.application.orchestration.solution_planning import (
    SolutionPlanningAgent,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.orchestration.profile_fused import (
    ProfilePlanningProjectionV1,
    ProfileReasonPlanOutputV1,
)
from google_work_agent.ports import WorkflowStartRequest


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
