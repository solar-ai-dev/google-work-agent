"""Deterministic Tool Route subgraph over the connector tool catalog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.graph_state import (
    TOOL_ROUTE_RESULT_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.subgraph_state import ToolRoutingLocalState
from google_work_agent.application.workflows import (
    GraphStateUpdateV1,
    MultiAgentGraphState,
    SupervisorDecisionV1,
    ToolRouteAgent,
    ToolRouteCoordinator,
    ToolRouteResultV1,
    WorkflowPhase,
    route_supervisor,
)
from google_work_agent.domain import ConnectorToolCatalog

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]


class ToolRoutingSubgraph:
    """Resolve, bind, freeze, and publish one canonical Tool Route plan."""

    def __init__(
        self,
        *,
        coordinator: ToolRouteCoordinator,
        semantic_agent: ToolRouteAgent,
        merge_decision: MergeDecision,
    ) -> None:
        self._coordinator = coordinator
        self._semantic_agent = semantic_agent
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            ToolRoutingLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("route", self._route_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "route")
        graph.add_edge("route", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="tool_routing_subgraph")

    def _route_node(self, state: ToolRoutingLocalState) -> ToolRoutingLocalState:
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        request = request_from_state(state)
        result = self._coordinator.route(
            request_intent=request_intent,
            previous_plan=state.get("tool_route_plan"),
            semantic_candidate_provider=lambda: self._semantic_agent.determine_semantic_candidate(
                request_intent=request_intent,
                request=request,
            ),
            select_tool=lambda **kwargs: self._semantic_agent.select_tool_if_needed(
                request=request, **kwargs
            ),
        )
        return {**state, TOOL_ROUTE_RESULT_KEY: result}

    def _finalize_node(self, state: ToolRoutingLocalState) -> ToolRoutingLocalState:
        result = cast(ToolRouteResultV1, state[TOOL_ROUTE_RESULT_KEY])
        decision = route_supervisor(
            phase=WorkflowPhase.TOOL_ROUTING,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        merged = cast(
            dict[str, object],
            self._merge_decision(
                state,
                {"workflow_phase": WorkflowPhase.TOOL_ROUTING.value},
                decision,
            ),
        )
        merged.pop(TOOL_ROUTE_RESULT_KEY, None)
        return cast(ToolRoutingLocalState, merged)


def build_tool_routing_subgraph(
    *,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    merge_decision: MergeDecision,
    semantic_agent: ToolRouteAgent,
) -> Any:
    """Build the Tool Route node at the LangGraph composition boundary."""

    return ToolRoutingSubgraph(
        coordinator=ToolRouteCoordinator(tool_catalog=tool_catalog, id_factory=id_factory),
        semantic_agent=semantic_agent,
        merge_decision=merge_decision,
    ).build()


__all__ = ["ToolRoutingSubgraph", "build_tool_routing_subgraph"]
