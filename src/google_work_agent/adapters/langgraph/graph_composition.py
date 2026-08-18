"""LangGraph node binding and graph composition for workflow profiles."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, replace
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.profiles import GraphProfile


@dataclass(frozen=True, slots=True)
class GraphNodeBindings:
    request_understanding: Any
    tool_route: Any
    acquisition: Any
    context_retriever: Any
    work_analysis: Any
    planning: Any
    review: Any
    single_workflow: Any
    domain_validation: Any
    waiting_confirmation: Any
    waiting_approval: Any
    modify_review: Any
    action_execution: Any
    recovery: Any
    finalize: Any
    stage_one: Any
    stage_two: Any
    stage_three: Any

    def for_name(self, name: str) -> Any:
        return {
            "request_understanding": self.request_understanding,
            "tool_route": self.tool_route,
            "acquisition": self.acquisition,
            "context_retriever": self.context_retriever,
            "work_analysis": self.work_analysis,
            "planning": self.planning,
            "review": self.review,
            "single_workflow": self.single_workflow,
            "domain_validation": self.domain_validation,
            "waiting_confirmation": self.waiting_confirmation,
            "waiting_approval": self.waiting_approval,
            "modify_review": self.modify_review,
            "action_execution": self.action_execution,
            "recovery": self.recovery,
            "finalize": self.finalize,
            "stage_one": self.stage_one,
            "stage_two": self.stage_two,
            "stage_three": self.stage_three,
        }[name]

    def native_for_profile(self, profile: GraphProfile) -> dict[str, Any]:
        names: tuple[str, ...]
        if profile is GraphProfile.SIX_ROLE_BASELINE:
            names = (
                "request_understanding",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            )
        elif profile is GraphProfile.THREE_STAGE:
            names = ("stage_one", "stage_two", "stage_three")
        else:
            names = ("single_workflow",)
        return {name: self.for_name(name) for name in names}


class WorkflowGraphComposition:
    def __init__(
        self,
        *,
        profile: GraphProfile,
        topology: tuple[str, ...],
        bindings: GraphNodeBindings,
        route_next_node: Callable[[GraphState], str],
        checkpointer: Any,
    ) -> None:
        self._profile = profile
        self._topology = topology
        self._bindings = bindings
        self._route_next_node = route_next_node
        self._checkpointer = checkpointer

    def build(self) -> Any:
        graph = StateGraph(GraphState)
        for name in self._topology:
            graph.add_node(name, self._bindings.for_name(name))
        for name in (
            "tool_route",
            "domain_validation",
            "waiting_confirmation",
            "waiting_approval",
            "modify_review",
            "action_execution",
            "recovery",
            "finalize",
        ):
            graph.add_node(name, self._bindings.for_name(name))
        graph.add_edge(START, self._topology[0])
        edges = self.edge_map()
        for name in (
            *self._topology,
            "tool_route",
            "domain_validation",
            "waiting_confirmation",
            "waiting_approval",
            "modify_review",
            "action_execution",
            "recovery",
            "finalize",
        ):
            graph.add_conditional_edges(name, self._route_next_node, edges)
        return graph.compile(checkpointer=self._checkpointer)

    def replace_binding(self, name: str, handler: Any) -> None:
        """Replace one registered node before recompiling the parent graph."""

        if name not in GraphNodeBindings.__dataclass_fields__:
            raise KeyError(f"unknown graph node binding: {name}")
        self._bindings = replace(self._bindings, **{name: handler})

    def edge_map(self) -> dict[Hashable, str]:
        edges: dict[Hashable, str] = {
            "tool_route": "tool_route",
            "domain_validation": "domain_validation",
            "waiting_confirmation": "waiting_confirmation",
            "waiting_approval": "waiting_approval",
            "modify_review": "modify_review",
            "action_execution": "action_execution",
            "recovery": "recovery",
            "finalize": "finalize",
            "end": END,
        }
        for name in self._topology:
            edges[name] = name
        return edges

    def node_handler(self, name: str) -> Any:
        return self._bindings.for_name(name)

    def native_subgraphs(self) -> dict[str, Any]:
        return self._bindings.native_for_profile(self._profile)
