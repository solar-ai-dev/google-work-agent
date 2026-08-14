"""Executable LangGraph state shape for the Stage 17/18 workflow runtime.

Moved out of ``runtime.py`` (Stage 3 of the LangGraph module cleanup) as a
pure type/constant/helper module with no behavior change: every definition
here is unchanged from its previous location, only its module changed.
"""
# Runtime type names below are retained for LangGraph's inherited TypedDict
# get_type_hints resolution, even when they are not referenced textually here.
# ruff: noqa: F401

from __future__ import annotations

from json import dumps
from typing import Final, NotRequired, cast

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.workflows import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    ContextBundleV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    MultiAgentGraphState,
    PlanReviewResultV1,
    RequestIntentV2,
    RequestUnderstandingOutputV1,
    RetrievalResultV1,
    RunBudgetV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyResultV2,
    WorkAnalysisResultV1,
    WorkflowPhase,
)
from google_work_agent.application.workflows.tool_routing import (
    RouteReconsiderationRequiredV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
    ToolRouteResultV1,
)
from google_work_agent.ports import (
    ResourceRefRecord,
    ResourceSource,
    StoredResourceType,
    WorkflowStartRequest,
)


class ParentGraphState(MultiAgentGraphState):
    """State projected from a native subgraph back to the parent graph."""

    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str
    __modify_review_plan_id__: NotRequired[str | None]
    __modify_review_version__: NotRequired[int | None]
    __modify_review_risks__: NotRequired[dict[str, dict[str, object]] | None]
    __replan_from_plan_id__: NotRequired[str]
    context_bundle: NotRequired[ContextBundleV1]
    evidence_drafts: NotRequired[list[EvidenceDraftV1]]
    llm_provider_result: NotRequired[dict[str, object] | None]


GraphState = ParentGraphState


REQUEST_AGENT_LOCAL_KEY: Final = "__request_agent_local__"
REQUEST_OUTPUT_KEY: Final = "__request_output__"
ACQUISITION_AGENT_LOCAL_KEY: Final = "__acquisition_agent_local__"
ACQUISITION_PLANNING_OUTPUT_KEY: Final = "__acquisition_planning_output__"
CONTEXT_AGENT_LOCAL_KEY: Final = "__context_agent_local__"
CONTEXT_RAG_CANDIDATES_KEY: Final = "__context_rag_candidates__"
CONTEXT_SELECTION_OUTPUT_KEY: Final = "__context_selection_output__"
CONTEXT_SUFFICIENCY_OUTPUT_KEY: Final = "__context_sufficiency_output__"
CONTEXT_CURRENT_ROUND_NO_KEY: Final = "__context_current_round_no__"
CONTEXT_READ_RESULT_HANDLES_KEY: Final = "__context_read_result_handles__"
CONTEXT_SEGMENT_HANDLES_KEY: Final = "__context_segment_handles__"
CONTEXT_QUERY_ATTEMPTS_KEY: Final = "__context_query_attempts__"
CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY: Final = "__context_followup_planner_input__"
ANALYSIS_AGENT_LOCAL_KEY: Final = "__analysis_agent_local__"
PLANNING_AGENT_LOCAL_KEY: Final = "__planning_agent_local__"
PLANNING_MODE_KEY: Final = "__planning_mode__"
TOOL_ROUTE_RESULT_KEY: Final = "__tool_route_result__"
REVIEW_AGENT_LOCAL_KEY: Final = "__review_agent_local__"
REVIEW_MODE_KEY: Final = "__review_mode__"
PROFILE_AGENT_LOCAL_KEY: Final = "__profile_agent_local__"
PROFILE_REQUEST_SOURCE_OUTPUT_KEY: Final = "__profile_request_source_output__"
PROFILE_REASON_PLAN_OUTPUT_KEY: Final = "__profile_reason_plan_output__"


def initial_graph_state(
    request: WorkflowStartRequest,
    *,
    graph_profile: GraphProfile,
    initial_target: str,
) -> GraphState:
    return {
        "schema_version": 1,
        "run_id": request.run_id,
        "conversation_id": request.conversation_id,
        "thread_id": request.workflow_key,
        "workflow_phase": WorkflowPhase.INITIALIZE.value,
        "request_intent": None,
        "tool_route_plan": None,
        "workflow_signal": None,
        "source_fetch_plans": [],
        "acquisition_result": None,
        "retrieval_result": None,
        "context_result": None,
        "analysis_result": None,
        "answer_draft": None,
        "plan_draft": None,
        "plan_review": None,
        "approved_plan_id": None,
        "execution_summary": None,
        "verification_summary": None,
        "finalize_intent": None,
        "user_interrupt": None,
        "retry_budget": {
            "schema_version": 1,
            "profile": "NORMAL",
            "llm_calls_used": 0,
            "additional_acquisitions_used": 0,
            "planning_revisions_used": 0,
            "last_rechecked_planning_revision": 0,
            "semantic_revision_signatures_used": [],
        },
        "prompt_context": {"graph_profile": graph_profile.value},
        "trace_context": {
            "agent_invocation_count": 0,
            "llm_call_count": 0,
            "repair_count": 0,
            "revision_count": 0,
            "agent_node_log": [],
            "prompt_refs": [],
        },
        "__request__": request,
        "__target__": initial_target,
        "__logical_target__": initial_target,
    }


def _require_state_value[StateValueT](
    value: StateValueT | None,
    field_name: str,
) -> StateValueT:
    if value is None:
        raise ValueError(f"graph state is missing required field: {field_name}")
    return value


def _resource_handle_for_ref(resource_ref: ResourceRefRecord) -> str:
    prefixes = {
        ("GMAIL", "THREAD"): "gmail_thread",
        ("GMAIL", "MESSAGE"): "gmail_message",
        ("TASKS", "TASK_LIST"): "task_list",
        ("TASKS", "TASK"): "task",
        ("CALENDAR", "CALENDAR"): "calendar",
        ("CALENDAR", "EVENT"): "calendar_event",
    }
    prefix = prefixes.get((resource_ref.source.value, resource_ref.resource_type.value))
    if prefix is None:
        raise LookupError(f"unsupported persisted resource reference: {resource_ref.id}")
    return f"{prefix}:{resource_ref.resource_id}"


def _acquired_resource_by_handle(
    *, acquisition_result: AcquisitionResultV1, resource_handle: str
) -> dict[str, object] | None:
    source_summaries = acquisition_result["source_summaries"]
    for summary in source_summaries:
        source = summary.get("source")
        resources = summary.get("resources")
        if not isinstance(source, str) or not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            if resource.get("resource_handle") != resource_handle:
                continue
            payload = resource.get("payload")
            if not isinstance(payload, dict):
                raise LookupError(f"acquired resource payload is invalid: {resource_handle}")
            return {**resource, "source": source, "payload": payload}
    return None


def request_from_state(state: GraphState) -> WorkflowStartRequest:
    request = state.get("__request__")
    if not isinstance(request, WorkflowStartRequest):
        raise TypeError("workflow state is missing WorkflowStartRequest")
    prompt_context = cast(dict[str, object], state.get("prompt_context", {}))
    confirmation_response = prompt_context.get("confirmation_response")
    if not isinstance(confirmation_response, dict):
        return request
    request_text = (
        request.request_text
        + "\n\n[clarification]\n"
        + dumps(
            {
                "selected_option_ids": cast(
                    list[str], confirmation_response.get("selected_option_ids", [])
                ),
                "free_text": cast(str | None, confirmation_response.get("free_text")),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return WorkflowStartRequest(
        run_id=request.run_id,
        conversation_id=request.conversation_id,
        workflow_key=request.workflow_key,
        entry_mode=request.entry_mode,
        requested_mode=request.requested_mode,
        request_text=request_text,
        selected_resource_ids=request.selected_resource_ids,
        correlation=request.correlation,
        selected_resources=request.selected_resources,
    )


def _stored_resource_type_for_acquired_resource(
    *, source: ResourceSource, resource_type: str
) -> StoredResourceType:
    mapping = {
        (ResourceSource.GMAIL, "gmail_thread"): StoredResourceType.THREAD,
        (ResourceSource.GMAIL, "gmail_message"): StoredResourceType.MESSAGE,
        (ResourceSource.TASKS, "task_list"): StoredResourceType.TASK_LIST,
        (ResourceSource.TASKS, "task"): StoredResourceType.TASK,
        (ResourceSource.CALENDAR, "calendar"): StoredResourceType.CALENDAR,
        (ResourceSource.CALENDAR, "calendar_event"): StoredResourceType.EVENT,
    }
    stored_type = mapping.get((source, resource_type))
    if stored_type is None:
        raise LookupError(f"unsupported acquired resource type: {source.value}/{resource_type}")
    return stored_type
