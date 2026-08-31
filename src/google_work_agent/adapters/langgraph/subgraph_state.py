"""Invocation-local state and parent-input projections for native agent subgraphs."""

# ParentGraphState carries deferred annotations; LangGraph resolves them in
# this module's namespace for each inherited local TypedDict.
# ruff: noqa: F401

from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import GraphState, RunInputV1
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
    PlanningActionSeedV1,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    AnswerOutlineV1,
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2 as CanonicalRequestIntentV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.resolve_availability import AvailableIntervalV1
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    CurrentSourceRelationV1,
    InformationGapAssessmentV1,
    OperationalRiskAssessmentV1,
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    MultiAgentGraphState,
    UserInterruptV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextBundleV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    RouteReconsiderationRequiredV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyResultV2,
    WorkflowSignalV1,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PlanningResultV2,
)
from google_work_agent.application.orchestration.retrieval_ranking import RagCandidateV1
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalQueryPlanV2,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    SourceFetchPlanV1 as V2SourceFetchPlanV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


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
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]
    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str
    __workflow_control__: dict[str, object] | None


class RequestUnderstandingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Request Understanding."""

    run_input: RunInputV1
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


class ToolRoutingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for semantic Tool Route and deterministic binding."""

    request_intent: CanonicalRequestIntentV2
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | RouteReconsiderationRequiredV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


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
    exclusion_obligation_segment_ids: list[str]
    pending_user_retrieval_need: RetrievalNeedV1 | None


class WorkAnalysisInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for evidence-grounded Work Analysis."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


class PlanningInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Planning and bounded Review-driven revision."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class ReviewInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection for Review inspect/recheck."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    planning_result: PlanningResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    __modify_review_plan_id__: str | None
    __modify_review_version__: int | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class AcquisitionLocalState(GraphState):
    __acquisition_agent_local__: NotRequired[AgentLocalStateV1]
    __acquisition_planning_output__: NotRequired[SourcePlanningOutputV1]


class ContextRetrievalLocalState(GraphState):
    # Exact RetrievalStateV2 semantic channels. The remaining fields below
    # are runtime envelope/scratch channels and are removed at the Parent
    # projection boundary.
    input_route_ref: NotRequired[StateArtifactRefV1]
    input_routes: NotRequired[list[InputToolRouteV1]]
    query_attempts: NotRequired[list[QueryAttemptV1]]
    source_statuses: NotRequired[list[RetrievalSourceStatusV1]]
    read_result_handles: NotRequired[list[str]]
    segment_handles: NotRequired[list[str]]
    rag_candidates: NotRequired[list[RagCandidateV1]]
    evidence_selection: NotRequired[EvidenceSelectionResultV2 | None]
    sufficiency: NotRequired[SufficiencyResultV2 | None]
    final_result: NotRequired[RetrievalResultV1 | None]
    context_bundle: NotRequired[ContextBundleV1]
    evidence_drafts: NotRequired[list[EvidenceDraftV1]]
    llm_provider_result: NotRequired[dict[str, object] | None]
    query_plan: NotRequired[RetrievalQueryPlanV2 | None]
    segments: NotRequired[list[str]]
    ranked_segments: NotRequired[list[RagCandidateV1]]
    availability_results: NotRequired[list[AvailableIntervalV1]]
    __context_agent_local__: NotRequired[AgentLocalStateV1]
    __context_rag_candidates__: NotRequired[list[RagCandidateV1]]
    __context_selection_output__: NotRequired[EvidenceSelectionResultV2]
    __context_sufficiency_output__: NotRequired[SufficiencyResultV2]
    __context_current_round_no__: NotRequired[int]
    __context_read_result_handles__: NotRequired[list[str]]
    __context_read_bindings__: NotRequired[dict[str, dict[str, str]]]
    __context_segment_handles__: NotRequired[list[str]]
    __context_query_attempts__: NotRequired[list[QueryAttemptV1]]
    __context_followup_planner_input__: NotRequired[dict[str, object]]
    __context_canonical_plans__: NotRequired[dict[str, V2SourceFetchPlanV1]]
    __context_followup_operation__: NotRequired[str]
    __context_next_page_handles__: NotRequired[dict[str, str]]
    __context_detail_candidates__: NotRequired[dict[str, str]]
    # Routes the self-loop conditional edge back into "finalize" as a fresh task.
    __context_retrieval_retry_confirmation__: NotRequired[bool]


class WorkAnalysisLocalState(GraphState):
    user_request: NotRequired[str]
    evidence: NotRequired[list[EvidenceDraftV1]]
    evidence_refs: NotRequired[list[str]]
    availability_results: NotRequired[list[dict[str, object]]]
    confirmation_response: NotRequired[dict[str, object]]
    current_source_relations: NotRequired[list[CurrentSourceRelationV1]]
    fact_candidates: NotRequired[list[WorkFactV1]]
    entity_relation_candidates: NotRequired[list[WorkRelationCandidateV1]]
    temporal_dependency_candidates: NotRequired[list[WorkRelationCandidateV1]]
    duplicate_conflict_candidates: NotRequired[list[WorkRelationCandidateV1]]
    validated_relations: NotRequired[list[WorkRelationV1]]
    relation_validation_ambiguities: NotRequired[list[WorkAmbiguityV1]]
    ambiguity_candidates: NotRequired[list[WorkAmbiguityV1]]
    retrieval_needs: NotRequired[list[RetrievalNeedV1]]
    operational_risk_candidates: NotRequired[list[WorkRiskV1]]
    final_analysis: NotRequired[WorkAnalysisResultV2 | None]
    __analysis_information_gap_assessment__: NotRequired[InformationGapAssessmentV1]
    __analysis_operational_risk_assessment__: NotRequired[OperationalRiskAssessmentV1]
    __analysis_noncomplete_disposition__: NotRequired[str]
    __analysis_agent_local__: NotRequired[AgentLocalStateV1]
    # Same purpose as ContextRetrievalLocalState's retry marker: routes the
    # self-loop back into "finalize" as a fresh task.
    __work_analysis_retry_confirmation__: NotRequired[bool]


class PlanningLocalState(GraphState):
    user_request: NotRequired[str]
    output_plan: NotRequired[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]
    evidence: NotRequired[list[EvidenceDraftV1]]
    evidence_refs: NotRequired[list[str]]
    confirmation_response: NotRequired[dict[str, object]]
    answer_outline: NotRequired[AnswerOutlineV1]
    planning_disposition: NotRequired[str]
    planning_confirmation: NotRequired[dict[str, object] | None]
    __planning_retry_outline__: NotRequired[bool]
    action_objective_candidates: NotRequired[list[ActionObjectiveCandidateV1]]
    argument_candidates: NotRequired[list[ToolArgumentCandidateV1]]
    dependency_candidates: NotRequired[list[ActionDependencyCandidateV1]]
    final_result: NotRequired[dict[str, object]]
    __planning_action_seeds__: NotRequired[list[PlanningActionSeedV1]]
    __planning_agent_local__: NotRequired[AgentLocalStateV1]
    __planning_mode__: NotRequired[str]
    __planning_result__: NotRequired[AnswerDraftV1 | ActionPlanDraftV1 | ActionPlanDraftV2]
    # Same purpose as the other native subgraphs' retry markers: routes the
    # self-loop conditional edge back into "finalize" as a fresh task for
    # the next confirmation round.
    __planning_retry_confirmation__: NotRequired[bool]


__all__ = [
    "AcquisitionLocalState",
    "AgentSubgraphInputEnvelope",
    "ContextRetrievalInputState",
    "ContextRetrievalLocalState",
    "PlanningInputState",
    "PlanningLocalState",
    "RequestUnderstandingInputState",
    "ReviewInputState",
    "ToolRoutingInputState",
    "WorkAnalysisInputState",
    "WorkAnalysisLocalState",
]
