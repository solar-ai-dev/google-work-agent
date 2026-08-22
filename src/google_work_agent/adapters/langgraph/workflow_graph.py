"""SIX_ROLE production graph topology for the atomic post-Retrieval V2 cut-over.

Legacy state fields remain present through ParentGraphState for pre-Retrieval,
experimental-profile and bounded compatibility code, but the compiled SIX_ROLE
post-Retrieval nodes own only the V2 fields declared here.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, NotRequired

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.checkpoint_secret_boundary import (
    SecretBoundaryCheckpointer,
)
from google_work_agent.adapters.langgraph.graph_state import ParentGraphState
from google_work_agent.application.orchestration.handoff_contracts import SubgraphReturnV2
from google_work_agent.application.orchestration.post_retrieval_envelopes import PlanningResultV2
from google_work_agent.application.orchestration.state_artifacts import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)


class ProductionGraphStateV2(ParentGraphState, total=False):
    """Official post-Retrieval Main State ownership for SIX_ROLE production."""

    work_analysis_result: NotRequired[WorkAnalysisResultV2 | None]
    planning_result: NotRequired[PlanningResultV2 | None]
    plan_review_result: NotRequired[PlanReviewResultV2 | None]
    post_retrieval_return: NotRequired[SubgraphReturnV2[object] | None]
    __v2_revision_mode__: NotRequired[str | None]
    __v2_block_reason__: NotRequired[str | None]


@dataclass(frozen=True, slots=True)
class ProductionV2NodeBindings:
    request_understanding: Any
    tool_route: Any
    context_retriever: Any
    work_analysis: Any
    planning: Any
    review: Any
    domain_validation: Any
    waiting_confirmation: Any
    waiting_approval: Any
    modify_review: Any
    action_execution: Any
    recovery: Any
    response_synthesis: Any
    block_run: Any
    domain_reconcile: Any
    finalize: Any

    def for_name(self, name: str) -> Any:
        return {
            "request_understanding": self.request_understanding,
            "tool_route": self.tool_route,
            "context_retriever": self.context_retriever,
            "work_analysis": self.work_analysis,
            "planning": self.planning,
            "review": self.review,
            "domain_validation": self.domain_validation,
            "waiting_confirmation": self.waiting_confirmation,
            "waiting_approval": self.waiting_approval,
            "modify_review": self.modify_review,
            "action_execution": self.action_execution,
            "recovery": self.recovery,
            "response_synthesis": self.response_synthesis,
            "block_run": self.block_run,
            "domain_reconcile": self.domain_reconcile,
            "finalize": self.finalize,
        }[name]


class ProductionV2GraphComposition:
    """Compiled SIX_ROLE topology with explicit BLOCK_RUN and DOMAIN_RECONCILE."""

    _TOPOLOGY = (
        "request_understanding",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
    )
    _COMMON = (
        "tool_route",
        "domain_validation",
        "waiting_confirmation",
        "waiting_approval",
        "modify_review",
        "action_execution",
        "recovery",
        "response_synthesis",
        "block_run",
        "domain_reconcile",
        "finalize",
    )

    def __init__(
        self,
        *,
        bindings: ProductionV2NodeBindings,
        route_next_node: Callable[[ProductionGraphStateV2], str],
        checkpointer: Any,
    ) -> None:
        self._bindings = bindings
        self._route_next_node = route_next_node
        self._checkpointer = (
            None
            if checkpointer is None
            else checkpointer
            if isinstance(checkpointer, SecretBoundaryCheckpointer)
            else SecretBoundaryCheckpointer(checkpointer)
        )

    def build(self) -> Any:
        graph = StateGraph(ProductionGraphStateV2)
        for name in (*self._TOPOLOGY, *self._COMMON):
            graph.add_node(name, self._bindings.for_name(name))
        graph.add_edge(START, self._TOPOLOGY[0])
        edges = self.edge_map()
        for name in (*self._TOPOLOGY, *self._COMMON):
            graph.add_conditional_edges(name, self._route_next_node, edges)
        return graph.compile(checkpointer=self._checkpointer)

    def edge_map(self) -> dict[Hashable, str]:
        edges: dict[Hashable, str] = {"end": END}
        for name in (*self._TOPOLOGY, *self._COMMON):
            edges[name] = name
        return edges

    def node_handler(self, name: str) -> Any:
        return self._bindings.for_name(name)

    def native_subgraphs(self) -> dict[str, Any]:
        return {name: self._bindings.for_name(name) for name in self._TOPOLOGY}


__all__ = [
    "ProductionGraphStateV2",
    "ProductionV2GraphComposition",
    "ProductionV2NodeBindings",
]
