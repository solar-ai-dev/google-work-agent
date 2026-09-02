"""Canonical Main LangGraph node binding and graph composition."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.checkpoint_secret_boundary import (
    SecretBoundaryCheckpointer,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_action_execution import (
    ROUTE_AFTER_ACTION_EXECUTION_SUCCESSORS,
    route_after_action_execution,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_cancel_resolution import (
    ROUTE_AFTER_CANCEL_RESOLUTION_SUCCESSORS,
    route_after_cancel_resolution,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_context_retriever import (
    ROUTE_AFTER_CONTEXT_RETRIEVER_SUCCESSORS,
    route_after_context_retriever,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_domain_reconcile import (
    ROUTE_AFTER_DOMAIN_RECONCILE_SUCCESSORS,
    route_after_domain_reconcile,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_domain_validation import (
    ROUTE_AFTER_DOMAIN_VALIDATION_SUCCESSORS,
    route_after_domain_validation,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_initialize import (
    ROUTE_AFTER_INITIALIZE_SUCCESSORS,
    route_after_initialize,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_planning import (
    ROUTE_AFTER_PLANNING_SUCCESSORS,
    route_after_planning,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_planning_entry import (
    ROUTE_AFTER_PLANNING_ENTRY_SUCCESSORS,
    route_after_planning_entry,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_preflight import (
    ROUTE_AFTER_PREFLIGHT_SUCCESSORS,
    route_after_preflight,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_recovery import (
    ROUTE_AFTER_RECOVERY_SUCCESSORS,
    route_after_recovery,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_request_understanding import (
    ROUTE_AFTER_REQUEST_UNDERSTANDING_SUCCESSORS,
    route_after_request_understanding,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_retrieval_entry import (
    ROUTE_AFTER_RETRIEVAL_ENTRY_SUCCESSORS,
    route_after_retrieval_entry,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_review import (
    ROUTE_AFTER_REVIEW_SUCCESSORS,
    route_after_review,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_review_entry import (
    ROUTE_AFTER_REVIEW_ENTRY_SUCCESSORS,
    route_after_review_entry,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_single_workflow import (
    ROUTE_AFTER_SINGLE_WORKFLOW_SUCCESSORS,
    route_after_single_workflow,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_stage_one import (
    ROUTE_AFTER_STAGE_ONE_SUCCESSORS,
    route_after_stage_one,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_stage_three import (
    ROUTE_AFTER_STAGE_THREE_SUCCESSORS,
    route_after_stage_three,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_stage_two import (
    ROUTE_AFTER_STAGE_TWO_SUCCESSORS,
    route_after_stage_two,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_tool_route import (
    ROUTE_AFTER_TOOL_ROUTE_SUCCESSORS,
    route_after_tool_route,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_verification import (
    ROUTE_AFTER_VERIFICATION_SUCCESSORS,
    route_after_verification,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_waiting_approval import (
    ROUTE_AFTER_WAITING_APPROVAL_SUCCESSORS,
    route_after_waiting_approval,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_work_analysis import (
    ROUTE_AFTER_WORK_ANALYSIS_SUCCESSORS,
    route_after_work_analysis,
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
        should_stop_for_cancel: Callable[[str], bool],
        checkpointer: Any,
    ) -> None:
        self._profile = profile
        self._topology = topology
        self._bindings = bindings
        self._control_bindings = control_bindings
        self._should_stop_for_cancel = should_stop_for_cancel
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
        for name, (router, successors) in self._stage_routers().items():
            closed_map: dict[Hashable, str] = {
                target: edges[target] for target in successors if target in edges
            }
            graph.add_conditional_edges(name, router, closed_map)
        graph.add_edge("response_synthesis", "terminal_commit")
        graph.add_edge("terminal_commit", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=self._checkpointer)

    def _stage_routers(self) -> dict[str, tuple[Callable[[GraphState], str], frozenset[str]]]:
        available_targets = frozenset(self.edge_map())
        agent_routers: dict[
            str,
            tuple[Callable[..., str], frozenset[str]],
        ] = {
            "request_understanding": (
                route_after_request_understanding,
                ROUTE_AFTER_REQUEST_UNDERSTANDING_SUCCESSORS,
            ),
            "tool_route": (route_after_tool_route, ROUTE_AFTER_TOOL_ROUTE_SUCCESSORS),
            "context_retriever": (
                route_after_context_retriever,
                ROUTE_AFTER_CONTEXT_RETRIEVER_SUCCESSORS,
            ),
            "work_analysis": (
                route_after_work_analysis,
                ROUTE_AFTER_WORK_ANALYSIS_SUCCESSORS,
            ),
            "planning": (route_after_planning, ROUTE_AFTER_PLANNING_SUCCESSORS),
            "review": (route_after_review, ROUTE_AFTER_REVIEW_SUCCESSORS),
            "single_workflow": (
                route_after_single_workflow,
                ROUTE_AFTER_SINGLE_WORKFLOW_SUCCESSORS,
            ),
            "stage_one": (route_after_stage_one, ROUTE_AFTER_STAGE_ONE_SUCCESSORS),
            "stage_two": (route_after_stage_two, ROUTE_AFTER_STAGE_TWO_SUCCESSORS),
            "stage_three": (route_after_stage_three, ROUTE_AFTER_STAGE_THREE_SUCCESSORS),
        }
        routers: dict[str, tuple[Callable[[GraphState], str], frozenset[str]]] = {}
        for name in self._topology:
            router, successors = agent_routers[name]
            routers[name] = (
                partial(
                    router,
                    available_targets=available_targets,
                    should_stop_for_cancel=self._should_stop_for_cancel,
                ),
                successors,
            )
        control_routers: dict[str, tuple[Callable[..., str], frozenset[str]]] = {
            "initialize": (route_after_initialize, ROUTE_AFTER_INITIALIZE_SUCCESSORS),
            "retrieval_entry": (
                route_after_retrieval_entry,
                ROUTE_AFTER_RETRIEVAL_ENTRY_SUCCESSORS,
            ),
            "planning_entry": (
                route_after_planning_entry,
                ROUTE_AFTER_PLANNING_ENTRY_SUCCESSORS,
            ),
            "review_entry": (route_after_review_entry, ROUTE_AFTER_REVIEW_ENTRY_SUCCESSORS),
            "domain_validation": (
                route_after_domain_validation,
                ROUTE_AFTER_DOMAIN_VALIDATION_SUCCESSORS,
            ),
            "preflight": (route_after_preflight, ROUTE_AFTER_PREFLIGHT_SUCCESSORS),
            "domain_reconcile": (
                route_after_domain_reconcile,
                ROUTE_AFTER_DOMAIN_RECONCILE_SUCCESSORS,
            ),
            "waiting_approval": (
                route_after_waiting_approval,
                ROUTE_AFTER_WAITING_APPROVAL_SUCCESSORS,
            ),
            "action_execution": (
                route_after_action_execution,
                ROUTE_AFTER_ACTION_EXECUTION_SUCCESSORS,
            ),
            "verification": (route_after_verification, ROUTE_AFTER_VERIFICATION_SUCCESSORS),
            "recovery": (route_after_recovery, ROUTE_AFTER_RECOVERY_SUCCESSORS),
            "cancel_resolution": (
                route_after_cancel_resolution,
                ROUTE_AFTER_CANCEL_RESOLUTION_SUCCESSORS,
            ),
        }
        routers.update(
            {
                name: (
                    partial(
                        router,
                        available_targets=available_targets,
                        should_stop_for_cancel=self._should_stop_for_cancel,
                    ),
                    successors,
                )
                for name, (router, successors) in control_routers.items()
            }
        )
        return routers

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
