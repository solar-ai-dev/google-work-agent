"""Request-understanding state with inherited LangGraph type resolution names."""

# LangGraph resolves inherited TypedDict annotations in this module namespace.
# ruff: noqa: F401

from __future__ import annotations

from typing import NotRequired

from google_work_agent.adapters.langgraph.subgraph_state import (
    RequestUnderstandingInputState,
    RequestUnderstandingLocalState,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    FinalizeIntentV1,
    PolicyConfirmationReceiptV1,
    RunBudgetV1,
    UserInterruptV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    PlanReviewResultV1,
    RetrievalRequiredV1,
    RetrievalResultV1,
    SourceFetchPlanV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.tool_routing import (
    RouteReconsiderationRequiredV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)


class RequestUnderstandingStateV2(RequestUnderstandingLocalState, total=False):
    """Owner-local working fields for Request Understanding only."""

    ru_candidate: NotRequired[RequestGoalCandidateV1]
    ru_ambiguity: NotRequired[AmbiguityV1]
    ru_intent: NotRequired[RequestIntentV2]
    ru_confirmation_response: NotRequired[ConfirmationResponseProjectionV1 | None]
    ru_invocation_id: NotRequired[str]
