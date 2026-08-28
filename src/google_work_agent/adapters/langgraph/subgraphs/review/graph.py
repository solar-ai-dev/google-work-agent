"""Canonical Review owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.aggregate_review_findings_node import (
    aggregate_review_findings_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_action_scope_and_route_node import (
    inspect_action_scope_and_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_constraints_and_policy_summary_node import (
    inspect_constraints_and_policy_summary_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_goal_and_evidence_node import (
    inspect_goal_and_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.recheck_affected_dimensions_node import (
    recheck_affected_dimensions_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.validate_review_node import (
    validate_review_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_entry import (
    route_after_entry,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_validation import (
    route_after_validation,
)
from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)


@dataclass(frozen=True, slots=True)
class ReviewRuntimeDependencies:
    """Infrastructure-only dependencies required by canonical Review operations."""

    invoke: ReviewSemanticInvoker


def _inactive_invoke(_prompt_id: str, _prompt_input: object) -> object:
    raise RuntimeError("review 0.9.2 prompts are not runtime-active")


class ReviewSubgraph:
    def __init__(
        self,
        *,
        dependencies: ReviewRuntimeDependencies | None = None,
        **_integration: Any,
    ) -> None:
        self._dependencies = dependencies or ReviewRuntimeDependencies(invoke=_inactive_invoke)  # type: ignore[arg-type]

    def build(self) -> Any:
        graph = StateGraph(ReviewState)
        graph.add_node(
            "inspect_goal_and_evidence",
            partial(inspect_goal_and_evidence_node, invoke=self._dependencies.invoke),
        )
        graph.add_node(
            "inspect_action_scope_and_route",
            partial(inspect_action_scope_and_route_node, invoke=self._dependencies.invoke),
        )
        graph.add_node(
            "inspect_constraints_and_policy_summary",
            partial(inspect_constraints_and_policy_summary_node, invoke=self._dependencies.invoke),
        )
        graph.add_node("aggregate_review_findings", aggregate_review_findings_node)
        graph.add_node("validate_review", validate_review_node)
        graph.add_node(
            "recheck_affected_dimensions",
            partial(recheck_affected_dimensions_node, invoke=self._dependencies.invoke),
        )
        graph.add_conditional_edges(
            START,
            route_after_entry,
            {
                "inspect_goal_and_evidence": "inspect_goal_and_evidence",
                "recheck_affected_dimensions": "recheck_affected_dimensions",
            },
        )
        graph.add_edge("inspect_goal_and_evidence", "inspect_action_scope_and_route")
        graph.add_edge("inspect_action_scope_and_route", "inspect_constraints_and_policy_summary")
        graph.add_edge("inspect_constraints_and_policy_summary", "aggregate_review_findings")
        graph.add_edge("recheck_affected_dimensions", "aggregate_review_findings")
        graph.add_edge("aggregate_review_findings", "validate_review")
        graph.add_conditional_edges(
            "validate_review",
            route_after_validation,
            {"end": END},
        )
        return graph.compile(name="review_subgraph")
