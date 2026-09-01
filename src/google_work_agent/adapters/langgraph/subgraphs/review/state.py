"""Review owner-local LangGraph state."""

# GraphState carries deferred annotations; LangGraph resolves them in this
# module's namespace for the inherited Review TypedDict.

from __future__ import annotations

from typing import Literal, NotRequired

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, RunInputV1
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentLocalStateV1,
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.planning.contracts.answer_draft import (
    WorkAnalysisResultV2,
)
from google_work_agent.application.agents.planning.contracts.planning_result import PlanningResultV2
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RetrievalResultV1,
)
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
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.terminal_contract import (
    FinalizeIntentV1,
)
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    UserInterruptV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.contracts.workflow_signal import (
    SubgraphReturnV2,
    WorkflowSignalV1,
)

_TYPE_HINT_NAMESPACE = (
    TerminalCommitIntentV1,
    RunInputV1,
    AcquisitionResultV1,
    ScopeExpansionRequiredV1,
    RunBudgetV2,
    PolicyConfirmationReceiptV1,
    FinalizeIntentV1,
    UserInterruptV1,
    WorkflowStartRequest,
    SubgraphReturnV2,
    WorkflowSignalV1,
)


class ReviewInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Review."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    planning_result: PlanningResultV2 | None
    plan_review: PlanReviewResultV2 | None
    __modify_review_plan_id__: str | None
    __modify_review_version__: int | None
    __modify_review_risks__: dict[str, dict[str, object]] | None


class ReviewState(GraphState, total=False):
    """Typed local state for the five canonical Review runtime nodes."""

    work_analysis: NotRequired[WorkAnalysisResultV2]
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


__all__ = ["ReviewInputState", "ReviewState"]
