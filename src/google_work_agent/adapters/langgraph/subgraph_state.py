"""Invocation-local state schemas for native agent subgraphs."""

# ParentGraphState carries deferred annotations; LangGraph resolves them in
# this module's namespace for each inherited local TypedDict.
# ruff: noqa: F401

from __future__ import annotations

from typing import NotRequired

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.workflows import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    ContextBundleV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    EvidenceSelectionOutputV1,
    MultiAgentGraphState,
    PlanReviewResultV1,
    RequestIntentV1,
    RequestUnderstandingOutputV1,
    RunBudgetV1,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyOutputV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.profile_fused import (
    ProfileReasonPlanOutputV1,
    ProfileRequestSourceOutputV1,
)
from google_work_agent.application.workflows.tool_routing import (
    RouteReconsiderationRequiredV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
    ToolRouteResultV1,
)
from google_work_agent.ports import WorkflowStartRequest


class RequestUnderstandingLocalState(GraphState):
    __request_agent_local__: NotRequired[AgentLocalStateV1]
    __request_output__: NotRequired[RequestUnderstandingOutputV1]


class ToolRoutingLocalState(GraphState):
    __tool_route_result__: NotRequired[ToolRouteResultV1]


class AcquisitionLocalState(GraphState):
    __acquisition_agent_local__: NotRequired[AgentLocalStateV1]
    __acquisition_planning_output__: NotRequired[SourcePlanningOutputV1]


class ContextRetrievalLocalState(GraphState):
    __context_agent_local__: NotRequired[AgentLocalStateV1]
    __context_selection_output__: NotRequired[EvidenceSelectionOutputV1]
    __context_sufficiency_output__: NotRequired[SufficiencyOutputV1]


class WorkAnalysisLocalState(GraphState):
    __analysis_agent_local__: NotRequired[AgentLocalStateV1]


class PlanningLocalState(GraphState):
    __planning_agent_local__: NotRequired[AgentLocalStateV1]
    __planning_mode__: NotRequired[str]
    __planning_result__: NotRequired[AnswerDraftV1 | ActionPlanDraftV1]


class ReviewLocalState(GraphState):
    __review_agent_local__: NotRequired[AgentLocalStateV1]
    __review_mode__: NotRequired[str]


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
