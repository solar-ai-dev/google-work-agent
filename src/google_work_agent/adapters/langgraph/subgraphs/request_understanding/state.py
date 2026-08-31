"""Canonical owner-local state and parent patch for Request Understanding."""

# LangGraph resolves inherited TypedDict annotations in this module namespace.
# ruff: noqa: F401

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import RunInputV1
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
    RequestIntentV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.ports.system.contracts.confirmation import (
    UserInterruptV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowStartRequest,
)


class RequestUnderstandingInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Request Understanding."""

    run_input: RunInputV1
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


class RequestUnderstandingStateV2(RequestUnderstandingInputState, total=False):
    """The exact 06-owned local fields plus the allowed parent patch channels."""

    request_text: str
    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    selected_resource_refs: list[SelectedResourceRef]
    goal_candidate: RequestGoalCandidateV1 | None
    ambiguity_candidate: AmbiguityV1 | None
    final_intent: RequestIntentV2 | None

    request_intent: RequestIntentV2 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    __workflow_control__: NotRequired[dict[str, object] | None]


class RequestUnderstandingParentOutputState(AgentSubgraphInputEnvelope, total=False):
    """Only fields that Request Understanding may project back to Main."""

    request_intent: RequestIntentV2 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    __workflow_control__: NotRequired[dict[str, object] | None]


__all__ = [
    "RequestUnderstandingInputState",
    "RequestUnderstandingParentOutputState",
    "RequestUnderstandingStateV2",
]
