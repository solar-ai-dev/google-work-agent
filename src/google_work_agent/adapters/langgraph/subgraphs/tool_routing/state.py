"""Canonical Tool Routing owner-local state and parent patch."""

# LangGraph resolves inherited TypedDict annotations in this module namespace.
# ruff: noqa: F401

from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentSubgraphInputEnvelope,
    ToolRoutingInputState,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    OutputToolRouteV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.terminal_contract import (
    FinalizeIntentV1,
)
from google_work_agent.ports.system.contracts.confirmation import (
    UserInterruptV1,
)


class ToolRouteStateV1(ToolRoutingInputState, total=False):
    """The exact 06-owned local fields plus allowed parent control channels."""

    request_intent: RequestIntentV2
    registry_snapshot_ref: str
    io_resource_candidate: SemanticRouteCandidate | None
    registry_candidates: list[BoundOutputRouteCandidateV1]
    bound_input_routes: list[InputToolRouteV1]
    bound_output_routes: list[OutputToolRouteV1]
    final_route: ToolRoutePlanV2 | None

    tool_route_plan: ToolRoutePlanV2 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    finalize_intent: FinalizeIntentV1 | None


class ToolRoutingParentOutputState(AgentSubgraphInputEnvelope, total=False):
    """Only fields that Tool Routing may project back to Main."""

    request_intent: RequestIntentV2
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    finalize_intent: FinalizeIntentV1 | None


__all__ = ["ToolRouteStateV1", "ToolRoutingInputState", "ToolRoutingParentOutputState"]
