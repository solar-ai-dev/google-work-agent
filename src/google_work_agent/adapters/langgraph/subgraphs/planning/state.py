"""Canonical semantic state owned by Planning."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentLocalStateV1,
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
    PlanningActionSeedV1,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    PlanningResultV2,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    RetrievalResultV1,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputPlanV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAnalysisResultV2,
)


class PlanningInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Planning."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    planning_result: PlanningResultV2 | None
    plan_review: PlanReviewResultV2 | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class PlanningLocalState(GraphState):
    """Planning-owned runtime channels used by its graph and nodes."""

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
    __planning_result__: NotRequired[PlanningResultV2]
    __planning_retry_confirmation__: NotRequired[bool]


class PlanningStateV2(TypedDict, total=False):
    user_request: str
    request_intent: RequestIntentV2
    output_plan: OutputPlanV1
    work_analysis: WorkAnalysisResultV2
    evidence_refs: list[str]
    action_objective_candidates: list[ActionObjectiveCandidateV1]
    argument_candidates: list[ToolArgumentCandidateV1]
    dependency_candidates: list[ActionDependencyCandidateV1]
    final_result: AnswerDraftCandidateV2 | ActionPlanDraftV2


__all__ = ["PlanningInputState", "PlanningLocalState", "PlanningStateV2"]
