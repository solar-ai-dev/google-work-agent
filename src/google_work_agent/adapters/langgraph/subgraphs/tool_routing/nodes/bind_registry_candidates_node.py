from __future__ import annotations

from collections.abc import Callable
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import bind_registry_candidates
from google_work_agent.domain import ConnectorToolCatalog
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.semantic_candidate_projection import project_semantic_candidate_input
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def bind_registry_candidates_node(state: ToolRoutingState, *, tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str]) -> ToolRoutingState:
    candidate = project_semantic_candidate_input(state)["candidate"]
    binding = bind_registry_candidates(candidate=candidate, tool_catalog=tool_catalog, id_factory=id_factory, selected_tools=state.get("tr_selected_tools", {}))
    return {"tr_binding": binding}
