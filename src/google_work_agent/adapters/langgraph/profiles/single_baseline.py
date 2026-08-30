"""SINGLE_BASELINE physical graph composition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.system.contracts.workflow_handoff import (
    CompiledAgentSubgraphIdV1,
    SemanticAgentOwnerIdV1,
)

SEMANTIC_OWNER_BINDINGS: dict[SemanticAgentOwnerIdV1, CompiledAgentSubgraphIdV1] = {
    "REQUEST_UNDERSTANDING": "UNIFIED_AGENT",
    "TOOL_ROUTE": "UNIFIED_AGENT",
    "RETRIEVAL": "UNIFIED_AGENT",
    "WORK_ANALYSIS": "UNIFIED_AGENT",
    "PLANNING": "UNIFIED_AGENT",
    "REVIEW": "UNIFIED_AGENT",
}


def build_single_baseline_graph(
    *,
    bindings: GraphNodeBindings,
    control_bindings: MainControlNodeBindings,
    route_next_node: Callable[[GraphState], str],
    checkpointer: Any,
) -> WorkflowGraphComposition:
    """Build the one-physical-subgraph profile over the shared Main Graph."""

    return WorkflowGraphComposition(
        profile=GraphProfile.SINGLE_BASELINE,
        topology=("single_workflow",),
        bindings=bindings,
        control_bindings=control_bindings,
        route_next_node=route_next_node,
        checkpointer=checkpointer,
    )
