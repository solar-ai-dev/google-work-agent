"""Canonical Main LangGraph node binding and graph composition."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.checkpoint_secret_boundary import (
    SecretBoundaryCheckpointer,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile


@dataclass(frozen=True, slots=True)
class GraphNodeBindings:
    request_understanding: Any
    tool_route: Any
    context_retriever: Any
    work_analysis: Any
    planning: Any
    review: Any
    single_workflow: Any
    waiting_approval: Any
    stage_one: Any
    stage_two: Any
    stage_three: Any

    def for_name(self, name: str) -> Any:
        return {
            "request_understanding": self.request_understanding,
            "tool_route": self.tool_route,
            "context_retriever": self.context_retriever,
            "work_analysis": self.work_analysis,
            "planning": self.planning,
            "review": self.review,
            "single_workflow": self.single_workflow,
            "waiting_approval": self.waiting_approval,
            "stage_one": self.stage_one,
            "stage_two": self.stage_two,
            "stage_three": self.stage_three,
        }[name]

    def native_for_profile(self, profile: GraphProfile) -> dict[str, Any]:
        names: tuple[str, ...]
        if profile is GraphProfile.SIX_ROLE_BASELINE:
            names = (
                "request_understanding",
                "tool_route",
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


@dataclass(frozen=True, slots=True)
class MainControlNodeBindings:
    """Exact bindings for canonical deterministic Main controls."""

    initialize: Any
    retrieval_entry: Any
    planning_entry: Any
    review_entry: Any
    domain_validation: Any
    preflight: Any
    domain_reconcile: Any
    action_execution: Any
    verification: Any
    recovery: Any
    cancel_resolution: Any
    response_synthesis: Any
    terminal_commit: Any
    finalize: Any

    def for_name(self, name: str) -> Any:
        return {
            "initialize": self.initialize,
            "retrieval_entry": self.retrieval_entry,
            "planning_entry": self.planning_entry,
            "review_entry": self.review_entry,
            "domain_validation": self.domain_validation,
            "preflight": self.preflight,
            "domain_reconcile": self.domain_reconcile,
            "action_execution": self.action_execution,
            "verification": self.verification,
            "recovery": self.recovery,
            "cancel_resolution": self.cancel_resolution,
            "response_synthesis": self.response_synthesis,
            "terminal_commit": self.terminal_commit,
            "finalize": self.finalize,
        }[name]


class WorkflowGraphComposition:
    def __init__(
        self,
        *,
        profile: GraphProfile,
        topology: tuple[str, ...],
        bindings: GraphNodeBindings,
        control_bindings: MainControlNodeBindings,
        route_next_node: Callable[[GraphState], str],
        checkpointer: Any,
    ) -> None:
        self._profile = profile
        self._topology = topology
        self._bindings = bindings
        self._control_bindings = control_bindings
        self._route_next_node = route_next_node
        self._checkpointer = (
            None
            if checkpointer is None
            else checkpointer
            if isinstance(checkpointer, SecretBoundaryCheckpointer)
            else SecretBoundaryCheckpointer(checkpointer)
        )

    def build(self) -> Any:
        graph = StateGraph(GraphState)
        agent_node_names = self._topology
        for name in agent_node_names:
            graph.add_node(name, self._bindings.for_name(name))
        for name in (
            "initialize",
            "retrieval_entry",
            "planning_entry",
            "review_entry",
            "domain_validation",
            "preflight",
            "domain_reconcile",
            "action_execution",
            "verification",
            "recovery",
            "cancel_resolution",
            "response_synthesis",
            "terminal_commit",
            "finalize",
        ):
            graph.add_node(name, self._control_bindings.for_name(name))
        for name in ("waiting_approval",):
            if name not in agent_node_names:
                graph.add_node(name, self._bindings.for_name(name))
        graph.add_edge(START, "initialize")
        edges = self.edge_map()
        for name in dict.fromkeys(
            (
                *self._topology,
                "initialize",
                "retrieval_entry",
                "planning_entry",
                "review_entry",
                "domain_validation",
                "preflight",
                "domain_reconcile",
                "waiting_approval",
                "action_execution",
                "verification",
                "recovery",
                "cancel_resolution",
                "response_synthesis",
                "terminal_commit",
                "finalize",
            )
        ):
            graph.add_conditional_edges(name, self._route_next_node, edges)
        return graph.compile(checkpointer=self._checkpointer)

    def edge_map(self) -> dict[Hashable, str]:
        edges: dict[Hashable, str] = {
            "retrieval_entry": "retrieval_entry",
            "planning_entry": "planning_entry",
            "review_entry": "review_entry",
            "domain_validation": "domain_validation",
            "preflight": "preflight",
            "domain_reconcile": "domain_reconcile",
            "waiting_approval": "waiting_approval",
            "action_execution": "action_execution",
            "verification": "verification",
            "recovery": "recovery",
            "cancel_resolution": "cancel_resolution",
            "response_synthesis": "response_synthesis",
            "terminal_commit": "terminal_commit",
            "finalize": "finalize",
            "end": END,
        }
        for name in self._topology:
            edges[name] = name
        return edges

    def node_handler(self, name: str) -> Any:
        if name in {
            "initialize",
            "retrieval_entry",
            "planning_entry",
            "review_entry",
            "domain_validation",
            "preflight",
            "domain_reconcile",
            "action_execution",
            "verification",
            "recovery",
            "cancel_resolution",
            "response_synthesis",
            "terminal_commit",
            "finalize",
        }:
            return self._control_bindings.for_name(name)
        return self._bindings.for_name(name)

    def native_subgraphs(self) -> dict[str, Any]:
        return self._bindings.native_for_profile(self._profile)
