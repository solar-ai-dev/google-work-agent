from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.binding_projection import (
    project_binding_input,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.orchestration.scope_expansion import ScopeExpansionResolver
from google_work_agent.domain.tool_registry import ConnectorToolCatalog


def finalize_route_node(
    state: ToolRoutingState,
    *,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    scope_expansion: ScopeExpansionResolver | None,
) -> ToolRoutingState:
    projection = project_binding_input(state)
    result = finalize_route(
        request_intent=projection["request_intent"],
        binding=projection["binding"],
        selected_tools=projection["selected_tools"],
        tool_catalog=tool_catalog,
        id_factory=id_factory,
        previous_plan=projection["previous_plan"],
        policy_confirmation_receipts=projection["policy_confirmation_receipts"],
        current_interrupt_id=state.get("tr_current_interrupt_id"),
        scope_expansion=scope_expansion,
    )
    return {"tr_result": result, "tr_current_interrupt_id": None}
