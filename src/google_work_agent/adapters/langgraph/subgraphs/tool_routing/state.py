from __future__ import annotations

from typing import NotRequired

from google_work_agent.adapters.langgraph.subgraph_state import ToolRoutingInputState, ToolRoutingLocalState
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import RouteBindingCandidateV1
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import SemanticRouteCandidate
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import ToolRouteResultV1
from google_work_agent.application.workflows import ConfirmationResponseV1, RunBudgetV1


class ToolRoutingState(ToolRoutingLocalState, total=False):
    """Owner-local working fields for Tool Routing only."""

    tr_semantic_candidate: NotRequired[SemanticRouteCandidate | None]
    tr_selected_tools: NotRequired[dict[tuple[str, str], str]]
    tr_binding: NotRequired[RouteBindingCandidateV1]
    tr_result: NotRequired[ToolRouteResultV1 | None]
    tr_confirmation_response: NotRequired[ConfirmationResponseV1 | None]
    tr_retry_budget: NotRequired[RunBudgetV1]
    tr_confirmation_origin: NotRequired[str]
    tr_current_interrupt_id: NotRequired[str | None]
