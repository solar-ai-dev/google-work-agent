"""SIX_ROLE_BASELINE physical graph composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.system.contracts.workflow_handoff import (
    CompiledAgentSubgraphIdV1,
    SemanticAgentOwnerIdV1,
)

SEMANTIC_OWNER_BINDINGS: Mapping[SemanticAgentOwnerIdV1, CompiledAgentSubgraphIdV1] = (
    MappingProxyType(
        {
            "REQUEST_UNDERSTANDING": "SIX_REQUEST_UNDERSTANDING",
            "TOOL_ROUTE": "SIX_TOOL_ROUTE",
            "RETRIEVAL": "SIX_RETRIEVAL",
            "WORK_ANALYSIS": "SIX_WORK_ANALYSIS",
            "PLANNING": "SIX_PLANNING",
            "REVIEW": "SIX_REVIEW",
        }
    )
)


def build_six_role_baseline_graph(
    *,
    bindings: GraphNodeBindings,
    control_bindings: MainControlNodeBindings,
    should_stop_for_cancel: Callable[[str], bool],
    checkpointer: Any,
) -> WorkflowGraphComposition:
    """Build the six-physical-subgraph profile over the shared Main Graph."""

    return WorkflowGraphComposition(
        profile=GraphProfile.SIX_ROLE_BASELINE,
        topology=(
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ),
        bindings=bindings,
        control_bindings=control_bindings,
        should_stop_for_cancel=should_stop_for_cancel,
        checkpointer=checkpointer,
    )
