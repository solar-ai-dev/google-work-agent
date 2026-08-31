"""Canonical Main LangGraph state and checkpoint projection helpers.

This module is the single repository owner for Main graph state. Subgraph-local
working state remains in each role's ``state.py`` and is projected through the
typed parent boundary.
"""
# Runtime type names below are retained for LangGraph's inherited TypedDict
# get_type_hints resolution, even when they are not referenced textually here.

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final, Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.agents.planning.contracts.answer_draft import (
    WorkAnalysisResultV2,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    PlanningResultV2,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    ContextRetrievalResultV1,
    EvidenceSelectionResultV2,
    RetrievalResultV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
    validate_run_budget_v2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.terminal_contract import (
    FinalizeIntentV1,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.resource_ref.model import ResourceSource
from google_work_agent.ports.system.contracts.confirmation import (
    UserInterruptV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
    SubgraphReturnV2,
    WorkflowSignalV1,
)

_TYPE_HINT_NAMESPACE = (
    request_understanding_output.RequestUnderstandingOutputV1,
    ContextRetrievalResultV1,
    EvidenceSelectionResultV2,
    SourcePlanningOutputV1,
    SufficiencyResultV2,
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
)


class MultiAgentGraphState(TypedDict):
    """Version-1 Main graph state retained at its canonical state owner."""

    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: WorkflowSignalV1 | ScopeExpansionRequiredV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    approved_plan_id: str | None
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]


class GraphStateUpdateV1(TypedDict, total=False):
    """Typed partial update returned by workflow agents and the supervisor."""

    workflow_phase: str
    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: WorkflowSignalV1 | ScopeExpansionRequiredV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    approved_plan_id: str | None
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]


class WorkflowPhase(StrEnum):
    """Workflow phase values defined by the Canonical workflow contract."""

    INITIALIZE = "INITIALIZE"
    REQUEST_ANALYSIS = "REQUEST_ANALYSIS"
    TOOL_ROUTING = "TOOL_ROUTING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SOURCE_PLANNING = "SOURCE_PLANNING"
    API_ACQUISITION = "API_ACQUISITION"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    CONTEXT_EVALUATION = "CONTEXT_EVALUATION"
    WORK_ANALYSIS = "WORK_ANALYSIS"
    SOLUTION_PLANNING = "SOLUTION_PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREFLIGHT = "PREFLIGHT"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    VERIFICATION = "VERIFICATION"
    RESPONSE_SYNTHESIS = "RESPONSE_SYNTHESIS"
    RECOVERY = "RECOVERY"
    FINALIZE = "FINALIZE"


class RequestUnderstandingResult(StrEnum):
    """Request-understanding node results."""

    COMPLETE = "COMPLETE"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    INVALID = "INVALID"


MULTI_AGENT_GRAPH_STATE_FIELDS = frozenset(MultiAgentGraphState.__annotations__)

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


class ExecutionSummaryV1(TypedDict):
    """Domain-backed execution fact projected solely for Main routing."""

    schema_version: Required[Literal[1]]
    action_id: str
    execution_attempt_id: str
    routing_outcome: Literal["EXECUTED", "FAILED", "UNKNOWN_RESULT"]
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    source_action_version: int


class VerificationSummaryV1(TypedDict):
    """Domain-backed verification fact projected solely for Main routing."""

    schema_version: Required[Literal[1]]
    action_id: str
    verification_id: str
    routing_outcome: Literal["VERIFIED", "MISMATCH"]
    source_action_version: int


class ParentGraphState(TypedDict):
    """State projected from a native subgraph back to the parent graph."""

    schema_version: Literal[2]
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: WorkflowSignalV1 | ScopeExpansionRequiredV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    approved_plan_id: str | None
    execution_summary: ExecutionSummaryV1 | None
    verification_summary: VerificationSummaryV1 | None
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]
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


def request_from_run_input_state(state: Mapping[str, object]) -> WorkflowStartRequest:
    """Rebuild the Request-Understanding input from immutable ``run_input``.

    Correlation identifiers remain runtime envelope metadata. User semantics,
    selected resources, mode, and budget come only from the current Run state.
    """
    envelope = request_from_state(state)
    raw_input = state.get("run_input")
    if not isinstance(raw_input, Mapping):
        raise TypeError("workflow state is missing RunInputV1")
    entry_mode = raw_input.get("entry_mode")
    user_request = raw_input.get("user_request")
    requested_mode = raw_input.get("requested_mode")
    raw_refs = raw_input.get("selected_resource_refs")
    if entry_mode not in {"AGENT_SEARCH", "RESOURCE_SELECTED"}:
        raise ValueError("run_input.entry_mode is invalid")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("run_input.user_request is required")
    if requested_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
        raise ValueError("run_input.requested_mode is invalid")
    if not isinstance(raw_refs, list):
        raise TypeError("run_input.selected_resource_refs must be a list")
    selected_resources: list[SelectedResourceRef] = []
    for index, raw_ref in enumerate(raw_refs):
        if not isinstance(raw_ref, Mapping):
            raise TypeError(f"run_input.selected_resource_refs[{index}] must be an object")
        source = raw_ref.get("source")
        resource_type = raw_ref.get("resource_type")
        resource_id = raw_ref.get("resource_id")
        parent_resource_id = raw_ref.get("parent_resource_id")
        if not isinstance(source, str) or not source:
            raise ValueError(f"run_input.selected_resource_refs[{index}] is incomplete")
        if not isinstance(resource_type, str) or not resource_type:
            raise ValueError(f"run_input.selected_resource_refs[{index}] is incomplete")
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError(f"run_input.selected_resource_refs[{index}] is incomplete")
        if parent_resource_id is not None and not isinstance(parent_resource_id, str):
            raise TypeError(
                f"run_input.selected_resource_refs[{index}].parent_resource_id must be a string"
            )
        selected_resources.append(
            SelectedResourceRef(
                source=source,
                resource_type=resource_type,
                resource_id=resource_id,
                parent_resource_id=parent_resource_id,
            )
        )
    run_budget = state.get("retry_budget")
    if not isinstance(run_budget, dict):
        raise TypeError("workflow state is missing RunBudgetV2")
    return WorkflowStartRequest(
        run_id=envelope.run_id,
        conversation_id=envelope.conversation_id,
        workflow_key=envelope.workflow_key,
        entry_mode=entry_mode,
        requested_mode=requested_mode,
        request_text=user_request,
        selected_resource_ids=tuple(item.resource_id for item in selected_resources),
        correlation=envelope.correlation,
        run_budget=dict(run_budget),
        selected_resources=tuple(selected_resources),
    )


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
