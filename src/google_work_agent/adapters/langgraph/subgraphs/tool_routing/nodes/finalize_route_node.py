from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.finalize_route_projection import (  # noqa: E501
    project_finalize_route_input,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry


def finalize_route_node(
    state: ToolRouteStateV1,
    *,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
) -> ToolRouteStateV1:
    projection = project_finalize_route_input(state)
    result = finalize_route(
        request_intent=projection["request_intent"],
        binding=projection["binding"],
        selected_tools=projection["selected_tools"],
        tool_catalog=tool_catalog,
        id_factory=id_factory,
        previous_plan=projection["previous_plan"],
    )
    return {"tr_result": result}
