"""THREE_STAGE physical graph composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
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

SEMANTIC_OWNER_BINDINGS: Mapping[SemanticAgentOwnerIdV1, CompiledAgentSubgraphIdV1] = (
    MappingProxyType(
        {
            "REQUEST_UNDERSTANDING": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "TOOL_ROUTE": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "RETRIEVAL": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "WORK_ANALYSIS": "STAGE_ANALYSIS_PLANNING",
            "PLANNING": "STAGE_ANALYSIS_PLANNING",
            "REVIEW": "STAGE_REVIEW",
        }
    )
)


def build_three_stage_graph(
    *,
    bindings: GraphNodeBindings,
    control_bindings: MainControlNodeBindings,
    route_next_node: Callable[[GraphState], str],
    checkpointer: Any,
) -> WorkflowGraphComposition:
    """Build the three-physical-subgraph profile over the shared Main Graph."""

    return WorkflowGraphComposition(
        profile=GraphProfile.THREE_STAGE,
        topology=("stage_one", "stage_two", "stage_three"),
        bindings=bindings,
        control_bindings=control_bindings,
        route_next_node=route_next_node,
        checkpointer=checkpointer,
    )
