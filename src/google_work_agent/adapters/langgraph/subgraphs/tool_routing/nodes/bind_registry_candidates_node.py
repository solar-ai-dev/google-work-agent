from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.semantic_candidate_projection import (  # noqa: E501
    project_semantic_candidate_input,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry


def bind_registry_candidates_node(
    state: ToolRoutingState, *, tool_catalog: SignedToolRegistry, id_factory: Callable[[], str]
) -> ToolRoutingState:
    candidate = project_semantic_candidate_input(state)["candidate"]
    binding = bind_registry_candidates(
        candidate=candidate, tool_catalog=tool_catalog, id_factory=id_factory
    )
    return {"tr_binding": binding}
