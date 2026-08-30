"""Canonical Main LangGraph state and checkpoint projection helpers.

This module is the single repository owner for Main graph state. Subgraph-local
working state remains in each role's ``state.py`` and is projected through the
typed parent boundary.
"""
# Runtime type names below are retained for LangGraph's inherited TypedDict
# get_type_hints resolution, even when they are not referenced textually here.
# ruff: noqa: F401

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RequestUnderstandingOutputV1,
    RetrievalRequiredV1,
    RetrievalResultV1,
    RouteReconsiderationRequiredV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SubgraphReturnV2,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PlanningResultV2,
)
from google_work_agent.application.orchestration.state_artifacts import WorkAnalysisResultV2
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
    validate_run_budget_v2,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.resource_ref.model import ResourceSource
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

type WorkflowPhaseV2 = Literal[
    "INITIALIZE",
    "REQUEST_UNDERSTANDING",
    "TOOL_ROUTING",
    "RETRIEVAL",
    "WORK_ANALYSIS",
    "PLANNING",
    "REVIEW",
    "DOMAIN_VALIDATION",
    "WAITING_CONFIRMATION",
    "WAITING_APPROVAL",
    "PREFLIGHT",
    "ACTION_EXECUTION",
    "READ_EXECUTION",
    "VERIFICATION",
    "RECOVERY",
    "RESPONSE_SYNTHESIS",
    "TERMINAL_COMMIT",
    "FINALIZE",
]


class RunInputV1(TypedDict):
    """Immutable user input projection for one Run."""

    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    user_request: str
    selected_resource_refs: list[dict[str, str | None]]
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]


class ParentGraphState(MultiAgentGraphState):
    """State projected from a native subgraph back to the parent graph."""

    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str
    __modify_review_plan_id__: NotRequired[str | None]
    __modify_review_version__: NotRequired[int | None]
    __modify_review_risks__: NotRequired[dict[str, dict[str, object]] | None]
    __replan_from_plan_id__: NotRequired[str]
    __reserved_corrective_plan_id__: NotRequired[str | None]


class MultiAgentGraphStateV2(ParentGraphState, total=False):
    """Canonical Main State plus bounded migration-only control projections."""

    schema_version: Required[Literal[2]]  # type: ignore[misc]
    langgraph_thread_id: Required[str]
    graph_profile: Required[Literal["SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"]]
    graph_version: Required[str]
    run_input: Required[RunInputV1]

    planning_result: NotRequired[PlanningResultV2 | None]
    post_retrieval_return: NotRequired[SubgraphReturnV2[object] | None]
    __v2_revision_mode__: NotRequired[str | None]
    __v2_block_reason__: NotRequired[str | None]
    __workflow_control__: NotRequired[dict[str, object] | None]
    exclusion_obligation_segment_ids: NotRequired[list[str]]
    pending_user_retrieval_need: NotRequired[dict[str, object] | None]
    terminal_commit_intent: NotRequired[TerminalCommitIntentV1 | None]


GraphState = MultiAgentGraphStateV2


ACQUISITION_AGENT_LOCAL_KEY: Final = "__acquisition_agent_local__"
ACQUISITION_PLANNING_OUTPUT_KEY: Final = "__acquisition_planning_output__"
CONTEXT_AGENT_LOCAL_KEY: Final = "__context_agent_local__"
CONTEXT_RAG_CANDIDATES_KEY: Final = "__context_rag_candidates__"
CONTEXT_SELECTION_OUTPUT_KEY: Final = "__context_selection_output__"
CONTEXT_SUFFICIENCY_OUTPUT_KEY: Final = "__context_sufficiency_output__"
CONTEXT_CURRENT_ROUND_NO_KEY: Final = "__context_current_round_no__"
CONTEXT_READ_RESULT_HANDLES_KEY: Final = "__context_read_result_handles__"
CONTEXT_READ_BINDINGS_KEY: Final = "__context_read_bindings__"
CONTEXT_SEGMENT_HANDLES_KEY: Final = "__context_segment_handles__"
CONTEXT_QUERY_ATTEMPTS_KEY: Final = "__context_query_attempts__"
CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY: Final = "__context_followup_planner_input__"
CONTEXT_CANONICAL_PLANS_KEY: Final = "__context_canonical_plans__"
CONTEXT_FOLLOWUP_OPERATION_KEY: Final = "__context_followup_operation__"
CONTEXT_NEXT_PAGE_HANDLES_KEY: Final = "__context_next_page_handles__"
CONTEXT_DETAIL_CANDIDATES_KEY: Final = "__context_detail_candidates__"
ANALYSIS_AGENT_LOCAL_KEY: Final = "__analysis_agent_local__"
PLANNING_AGENT_LOCAL_KEY: Final = "__planning_agent_local__"
PLANNING_MODE_KEY: Final = "__planning_mode__"
REVIEW_AGENT_LOCAL_KEY: Final = "__review_agent_local__"
REVIEW_MODE_KEY: Final = "__review_mode__"


def initial_graph_state(
    request: WorkflowStartRequest,
    *,
    graph_profile: GraphProfile,
    graph_version: str,
    initial_target: str,
) -> GraphState:
    return {
        "schema_version": 2,
        "run_id": request.run_id,
        "conversation_id": request.conversation_id,
        "thread_id": request.workflow_key,
        "langgraph_thread_id": request.workflow_key,
        "graph_profile": graph_profile.value,
        "graph_version": graph_version,
        "run_input": {
            "entry_mode": cast(Literal["AGENT_SEARCH", "RESOURCE_SELECTED"], request.entry_mode),
            "user_request": request.request_text,
            "selected_resource_refs": [
                {
                    "source": item.source,
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "parent_resource_id": item.parent_resource_id,
                }
                for item in request.selected_resources
            ],
            "requested_mode": cast(Literal["AUTO", "LOCAL_GPU", "API_LLM"], request.requested_mode),
        },
        "workflow_phase": WorkflowPhase.INITIALIZE.value,
        "request_intent": None,
        "tool_route_plan": None,
        "workflow_signal": None,
        "source_fetch_plans": [],
        "acquisition_result": None,
        "retrieval_result": None,
        "context_result": None,
        "work_analysis_result": None,
        "answer_draft": None,
        "plan_draft": None,
        "plan_review": None,
        "approved_plan_id": None,
        "execution_summary": None,
        "verification_summary": None,
        "finalize_intent": None,
        "terminal_commit_intent": None,
        "user_interrupt": None,
        "policy_confirmation_receipts": [],
        "retry_budget": validate_run_budget_v2(request.run_budget),
        "prompt_context": {},
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
    if resource_ref.resource_type not in {
        "gmail_thread",
        "gmail_message",
        "gmail_draft",
        "task_list",
        "task",
        "calendar",
        "calendar_event",
        "calendar_freebusy",
    }:
        raise LookupError(f"unsupported persisted resource reference: {resource_ref.id}")
    return f"{resource_ref.resource_type}:{resource_ref.resource_id}"


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


def request_from_state(state: Mapping[str, object]) -> WorkflowStartRequest:
    request = state.get("__request__")
    if not isinstance(request, WorkflowStartRequest):
        raise TypeError("workflow state is missing WorkflowStartRequest")
    return request


def _stored_resource_type_for_acquired_resource(
    *, source: ResourceSource, resource_type: str
) -> str:
    valid_pairs = {
        (ResourceSource.GMAIL, "gmail_thread"),
        (ResourceSource.GMAIL, "gmail_message"),
        (ResourceSource.TASKS, "task_list"),
        (ResourceSource.TASKS, "task"),
        (ResourceSource.CALENDAR, "calendar"),
        (ResourceSource.CALENDAR, "calendar_event"),
    }
    if (source, resource_type) not in valid_pairs:
        raise LookupError(f"unsupported acquired resource type: {source.value}/{resource_type}")
    return resource_type
