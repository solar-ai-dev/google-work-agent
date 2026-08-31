from __future__ import annotations

from collections.abc import Callable

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    resolve_policy_preconditions,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

from ..projections.bind_registry_candidates_projection import (
    project_bind_registry_candidates_input,
)


def bind_registry_candidates_node(
    state: ToolRouteStateV1, *, tool_catalog: SignedToolRegistry, id_factory: Callable[[], str]
) -> ToolRouteStateV1:
    projection = project_bind_registry_candidates_input(state)
    resolution = resolve_policy_preconditions(
        request_intent=projection["request_intent"],
        candidate=projection["candidate"],
        policy_confirmation_receipts=projection["policy_confirmation_receipts"],
        current_interrupt_id=projection["current_interrupt_id"],
    )
    if resolution.workflow_signal is not None:
        return {
            "registry_candidates": [],
            "bound_input_routes": [],
            "bound_output_routes": [],
            "workflow_signal": resolution.workflow_signal,
        }
    binding = bind_registry_candidates(
        candidate=resolution.candidate,
        tool_catalog=tool_catalog,
        id_factory=id_factory,
    )
    return {
        "io_resource_candidate": resolution.candidate,
        "registry_candidates": list(binding.output_candidates),
        "bound_input_routes": [route.copy() for route in binding.input_routes],
        "bound_output_routes": [],
        "workflow_signal": None,
    }
