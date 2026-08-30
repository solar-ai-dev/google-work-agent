"""THREE_STAGE physical composition over canonical semantic subgraphs."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.main.state import GraphState


class _SemanticStageSubgraph:
    def __init__(self, *, name: str, nodes: dict[str, Any]) -> None:
        self._name = name
        self._nodes = nodes

    def build(self) -> Any:
        graph = StateGraph(GraphState)
        for name, node in self._nodes.items():
            graph.add_node(name, node)
            graph.add_edge(name, END)
        graph.add_conditional_edges(START, self._entry, {name: name for name in self._nodes})
        return graph.compile(name=self._name)

    def _entry(self, state: GraphState) -> str:
        target = state.get("__logical_target__")
        if target in {"stage_one", "stage_two"}:
            return next(iter(self._nodes))
        if target not in self._nodes:
            raise ValueError(f"{self._name} has no semantic target {target!r}")
        return target


class ThreeStageOneSubgraph(_SemanticStageSubgraph):
    """Compose Request Understanding, Tool Routing, and Retrieval."""

    def __init__(
        self,
        *,
        request_understanding: Any,
        tool_route: Any,
        retrieval: Any,
    ) -> None:
        super().__init__(
            name="three_stage_one_subgraph",
            nodes={
                "request_understanding": request_understanding,
                "tool_route": tool_route,
                "context_retriever": retrieval,
            },
        )


class ThreeStageTwoSubgraph(_SemanticStageSubgraph):
    """Compose Work Analysis and Planning."""

    def __init__(self, *, work_analysis: Any, planning: Any) -> None:
        super().__init__(
            name="three_stage_two_subgraph",
            nodes={"work_analysis": work_analysis, "planning": planning},
        )


__all__ = ["ThreeStageOneSubgraph", "ThreeStageTwoSubgraph"]
