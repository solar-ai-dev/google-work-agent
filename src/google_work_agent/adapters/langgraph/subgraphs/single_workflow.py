"""SINGLE_BASELINE physical composition over canonical semantic subgraphs."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.main.state import GraphState


class SingleWorkflowSubgraph:
    """Compose six semantic authorities as one physical profile subgraph.

    This class owns topology only. Product prompts, validation, and semantic
    state transitions remain owned by the six canonical subgraphs supplied by
    the composition root.
    """

    def __init__(
        self,
        *,
        request_understanding: Any,
        tool_route: Any,
        retrieval: Any,
        work_analysis: Any,
        planning: Any,
        review: Any,
    ) -> None:
        self._nodes = {
            "request_understanding": request_understanding,
            "tool_route": tool_route,
            "context_retriever": retrieval,
            "work_analysis": work_analysis,
            "planning": planning,
            "review": review,
        }

    def build(self) -> Any:
        graph = StateGraph(GraphState)
        for name, node in self._nodes.items():
            graph.add_node(name, node)
            graph.add_edge(name, END)
        graph.add_conditional_edges(START, self._entry, {name: name for name in self._nodes})
        return graph.compile(name="single_workflow_subgraph")

    @staticmethod
    def _entry(state: GraphState) -> str:
        target = state.get("__logical_target__")
        if target == "single_workflow":
            return "request_understanding"
        if target not in {
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        }:
            raise ValueError(f"SINGLE_BASELINE has no semantic target {target!r}")
        return target


__all__ = ["SingleWorkflowSubgraph"]
