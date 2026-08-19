"""Invocation-local state and parent-input projections for native agent subgraphs."""

# ParentGraphState carries deferred annotations; LangGraph resolves them in
# this module's namespace for each inherited local TypedDict.
# ruff: noqa: F401

from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.graph_state import GraphState
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
    RetrievalRequiredV1,
    RetrievalResultV1,
    RunBudgetV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyResultV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.profile_fused import (
    ProfileReasonPlanOutputV1,
    ProfileRequestSourceOutputV1,
)
from google_work_agent.application.workflows.retrieval_attempts import QueryAttempt
from google_work_agent.application.workflows.retrieval_ranking import RagCandidateV1
from google_work_agent.application.workflows.retrieval_v2_contracts import (
    SourceFetchPlanV1 as V2SourceFetchPlanV1,
)
from google_work_agent.application.workflows.tool_routing import (
    RouteReconsiderationRequiredV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
    ToolRouteResultV1,
)
from google_work_agent.ports import WorkflowStartRequest


class AgentSubgraphInputEnvelope(TypedDict, total=False):
    """Runtime-only envelope shared by all native agent subgraph projections.

    This is intentionally not ``GraphState``. It contains only correlation,
    budget, prompt/trace context, and registered routing metadata required to
    execute/resume one subgraph invocation. Business artifacts are declared by
    the role-specific projections below.
    """

    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    retry_budget: RunBudgetV1
    prompt_context: dict[str, object]
    trace_context: dict[str, object]
    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str


class RequestUnderstandingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Request Understanding."""


class ToolRoutingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for semantic Tool Route and deterministic binding."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | RouteReconsiderationRequiredV1 | None


class ContextRetrievalInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Retrieval V2 plus legacy read compatibility inputs."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: (
        ScopeExpansionRequiredV1 | RouteReconsiderationRequiredV1 | RetrievalRequiredV1 | None
    )
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    context_result: ContextRetrievalResultV1 | None


class WorkAnalysisInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for evidence-grounded Work Analysis."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    context_result: ContextRetrievalResultV1 | None


class PlanningInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Planning and bounded Review-driven revision."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    analysis_result: WorkAnalysisResultV1 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV1 | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class ReviewInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Review inspect/recheck."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    analysis_result: WorkAnalysisResultV1 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV1 | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class RequestUnderstandingLocalState(GraphState):
    __request_agent_local__: NotRequired[AgentLocalStateV1]
    __request_output__: NotRequired[RequestUnderstandingOutputV1]
    # Set only when a resolved-but-still-ambiguous confirmation round needs
    # another nested interrupt: routes the self-loop conditional edge back
    # into "finalize" as a genuinely new task (never consumed outside this
    # subgraph -- explicitly popped before the final merge_decision return).
    __request_understanding_retry_confirmation__: NotRequired[bool]


class ToolRoutingLocalState(GraphState):
    __tool_route_result__: NotRequired[ToolRouteResultV1]
    # Same purpose as RequestUnderstandingLocalState's retry marker: routes
    # the self-loop conditional edge back into "finalize" as a fresh task
    # for the next confirmation round.
    __tool_route_retry_confirmation__: NotRequired[bool]


class AcquisitionLocalState(GraphState):
    __acquisition_agent_local__: NotRequired[AgentLocalStateV1]
    __acquisition_planning_output__: NotRequired[SourcePlanningOutputV1]


class ContextRetrievalLocalState(GraphState):
    __context_agent_local__: NotRequired[AgentLocalStateV1]
    __context_rag_candidates__: NotRequired[list[RagCandidateV1]]
    __context_selection_output__: NotRequired[EvidenceSelectionResultV2]
    __context_sufficiency_output__: NotRequired[SufficiencyResultV2]
    __context_current_round_no__: NotRequired[int]
    __context_read_result_handles__: NotRequired[list[str]]
    __context_segment_handles__: NotRequired[list[str]]
    __context_query_attempts__: NotRequired[list[QueryAttempt]]
    __context_followup_planner_input__: NotRequired[dict[str, object]]
    __context_canonical_plans__: NotRequired[dict[str, V2SourceFetchPlanV1]]
    __context_followup_operation__: NotRequired[str]
    __context_next_page_handles__: NotRequired[dict[str, str]]
    __context_detail_candidates__: NotRequired[dict[str, str]]
    # Same purpose as ToolRoutingLocalState/RequestUnderstandingLocalState's
    # retry markers: routes the self-loop conditional edge back into
    # "finalize" as a fresh task for the next confirmation round.
    __context_retrieval_retry_confirmation__: NotRequired[bool]


class WorkAnalysisLocalState(GraphState):
    __analysis_agent_local__: NotRequired[AgentLocalStateV1]
    # Same purpose as ContextRetrievalLocalState/ToolRoutingLocalState/
    # RequestUnderstandingLocalState's retry markers: routes the self-loop
    # conditional edge back into "finalize" as a fresh task for the next
    # confirmation round.
    __work_analysis_retry_confirmation__: NotRequired[bool]


class PlanningLocalState(GraphState):
    __planning_agent_local__: NotRequired[AgentLocalStateV1]
    __planning_mode__: NotRequired[str]
    __planning_result__: NotRequired[AnswerDraftV1 | ActionPlanDraftV1]
    # Same purpose as the other native subgraphs' retry markers: routes the
    # self-loop conditional edge back into "finalize" as a fresh task for
    # the next confirmation round.
    __planning_retry_confirmation__: NotRequired[bool]


class ReviewLocalState(GraphState):
    __review_agent_local__: NotRequired[AgentLocalStateV1]
    __review_mode__: NotRequired[str]
    # Same purpose as the other native subgraphs' retry markers: routes the
    # self-loop conditional edge back into "finalize" as a fresh task for
    # the next confirmation round.
    __review_retry_confirmation__: NotRequired[bool]


class ProfileRequestSourceLocalState(GraphState):
    __profile_agent_local__: NotRequired[AgentLocalStateV1]
    __profile_request_source_output__: NotRequired[ProfileRequestSourceOutputV1]


class ProfileReasonPlanLocalState(GraphState):
    __profile_agent_local__: NotRequired[AgentLocalStateV1]
    __profile_reason_plan_output__: NotRequired[ProfileReasonPlanOutputV1]


class SingleWorkflowLocalState(GraphState):
    """Local state for the fused request/source/reason/review subgraph."""

    __profile_agent_local__: NotRequired[AgentLocalStateV1]
    __profile_request_source_output__: NotRequired[ProfileRequestSourceOutputV1]
    __profile_reason_plan_output__: NotRequired[ProfileReasonPlanOutputV1]


__all__ = [
    "AcquisitionLocalState",
    "AgentSubgraphInputEnvelope",
    "ContextRetrievalInputState",
    "ContextRetrievalLocalState",
    "PlanningInputState",
    "PlanningLocalState",
    "ProfileReasonPlanLocalState",
    "ProfileRequestSourceLocalState",
    "RequestUnderstandingInputState",
    "RequestUnderstandingLocalState",
    "ReviewInputState",
    "ReviewLocalState",
    "SingleWorkflowLocalState",
    "ToolRoutingInputState",
    "ToolRoutingLocalState",
    "WorkAnalysisInputState",
    "WorkAnalysisLocalState",
]
