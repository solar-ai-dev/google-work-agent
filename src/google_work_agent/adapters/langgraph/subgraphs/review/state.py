"""Review owner-local LangGraph state."""

# GraphState carries deferred annotations; LangGraph resolves them in this
# module's namespace for the inherited Review TypedDict.
# ruff: noqa: F401

from __future__ import annotations

from typing import Literal, NotRequired

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, RunInputV1
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewInspectorFindingV1,
    ReviewInspectorResultV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    FinalizeIntentV1,
    PolicyConfirmationReceiptV1,
    UserInterruptV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    EvidenceDraftV1,
    RequestIntentV2,
    RetrievalResultV1,
    SourceFetchPlanV1,
    SubgraphReturnV2,
    WorkflowSignalV1,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PlanningResultV2,
)
from google_work_agent.application.orchestration.state_artifacts import WorkAnalysisResultV2
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class ReviewState(GraphState, total=False):
    """Typed local state for the five canonical Review runtime nodes."""

    work_analysis: NotRequired[WorkAnalysisResultV2]
    planning_result: NotRequired[PlanningResultV2 | None]
    evidence: NotRequired[list[EvidenceDraftV1]]
    policy_summary: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[ConfirmationResponseProjectionV1]
    review_phase: NotRequired[Literal["INITIAL", "RECHECK"]]
    review_artifact_id: NotRequired[str]
    review_revision: NotRequired[int]
    review_based_on: NotRequired[list[StateArtifactRefV1]]
    prior_review_findings: NotRequired[list[ReviewInspectorFindingV1]]
    affected_dimensions: NotRequired[list[ReviewDimensionIdV1]]
    affected_action_ids: NotRequired[list[str]]
    affected_route_ids: NotRequired[list[str]]
    goal_evidence_result: NotRequired[ReviewInspectorResultV1]
    action_scope_route_result: NotRequired[ReviewInspectorResultV1]
    constraints_policy_result: NotRequired[ReviewInspectorResultV1]
    affected_dimension_recheck: NotRequired[list[ReviewInspectorFindingV1]]
    review_result: NotRequired[PlanReviewResultV2]
    __review_agent_local__: NotRequired[AgentLocalStateV1]
    __review_mode__: NotRequired[str]
    __review_retry_confirmation__: NotRequired[bool]


__all__ = ["ReviewState"]
