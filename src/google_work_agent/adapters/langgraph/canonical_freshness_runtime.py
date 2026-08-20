"""Canonical downstream-artifact freshness compatibility boundary.

Until Main State V2 moves every downstream artifact onto ``meta.based_on``
freshness, the legacy Supervisor still clears downstream fields explicitly on
route reconsideration. It omitted the canonical ``retrieval_result`` field,
leaving an old RetrievalResult alive while Tool Route was being recomputed.

This release wrapper fixes only that omission. It does not become a new general
hard-coded invalidation authority; the full based_on migration remains the
owner of eventual freshness semantics.
"""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.canonical_response_runtime import (
    LangGraphWorkflowRuntime as _CanonicalResponseRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.workflows import (
    GraphStateUpdateV1,
    SupervisorDecisionV1,
    SupervisorTarget,
)


class LangGraphWorkflowRuntime(_CanonicalResponseRuntime):
    """Release runtime that drops stale RetrievalResult on route reconsideration."""

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        merged = super()._merge_decision(state, update, decision)
        if _is_route_reconsideration_to_tool_route(merged):
            return {**merged, "retrieval_result": None}
        return merged


def _is_route_reconsideration_to_tool_route(state: GraphState) -> bool:
    if state.get("__logical_target__") != SupervisorTarget.TOOL_ROUTE.value:
        return False
    signal = state.get("workflow_signal")
    return isinstance(signal, Mapping) and signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"


__all__ = ["LangGraphWorkflowRuntime"]
