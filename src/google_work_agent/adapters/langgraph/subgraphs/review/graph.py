"""Canonical Review owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.aggregate_review_findings_node import aggregate_review_findings_node
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_action_scope_and_route_node import inspect_action_scope_and_route_node
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_constraints_and_policy_summary_node import inspect_constraints_and_policy_summary_node
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_goal_and_evidence_node import inspect_goal_and_evidence_node
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.recheck_affected_dimensions_node import recheck_affected_dimensions_node
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.validate_review_node import validate_review_node
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_validation import route_after_validation
from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState


@dataclass(frozen=True, slots=True)
class ReviewNodeBindings:
    """Application operations injected into canonical thin node modules."""

    inspect_goal_and_evidence: Callable[[object], object]
    inspect_action_scope_and_route: Callable[[object], object]
    inspect_constraints_and_policy_summary: Callable[[object], object]
    aggregate_review_findings: Callable[[object], object]
    validate_review: Callable[[object], object]
    recheck_affected_dimensions: Callable[[object], object]


class ReviewSubgraph:
    def __init__(self, *, bindings: ReviewNodeBindings | None = None, **_integration: Any) -> None:
        self._bindings = bindings

    def build(self) -> Any:
        if self._bindings is None:
            def inactive(_value: object) -> object:
                raise RuntimeError("review 0.9.2 semantic operations are not runtime-active")
            bindings = ReviewNodeBindings(*(inactive for _ in range(6)))
        else:
            bindings = self._bindings

        graph = StateGraph(ReviewState)
        graph.add_node("inspect_goal_and_evidence", partial(inspect_goal_and_evidence_node, operation=bindings.inspect_goal_and_evidence))
        graph.add_node("inspect_action_scope_and_route", partial(inspect_action_scope_and_route_node, operation=bindings.inspect_action_scope_and_route))
        graph.add_node("inspect_constraints_and_policy_summary", partial(inspect_constraints_and_policy_summary_node, operation=bindings.inspect_constraints_and_policy_summary))
        graph.add_node("aggregate_review_findings", partial(aggregate_review_findings_node, operation=bindings.aggregate_review_findings))
        graph.add_node("validate_review", partial(validate_review_node, operation=bindings.validate_review))
        graph.add_node("recheck_affected_dimensions", partial(recheck_affected_dimensions_node, operation=bindings.recheck_affected_dimensions))
        graph.add_edge(START, "inspect_goal_and_evidence")
        graph.add_edge("inspect_goal_and_evidence", "inspect_action_scope_and_route")
        graph.add_edge("inspect_action_scope_and_route", "inspect_constraints_and_policy_summary")
        graph.add_edge("inspect_constraints_and_policy_summary", "aggregate_review_findings")
        graph.add_edge("aggregate_review_findings", "validate_review")
        graph.add_conditional_edges(
            "validate_review",
            route_after_validation,
            {"recheck_affected_dimensions": "recheck_affected_dimensions", "end": END},
        )
        graph.add_edge("recheck_affected_dimensions", END)
        return graph.compile(name="review_subgraph")
