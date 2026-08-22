"""Canonical Review owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState


@dataclass(frozen=True, slots=True)
class ReviewNodeBindings:
    inspect_goal_and_evidence: Callable[[ReviewState], dict[str, object]]
    inspect_action_scope_and_route: Callable[[ReviewState], dict[str, object]]
    inspect_constraints_and_policy_summary: Callable[[ReviewState], dict[str, object]]
    aggregate_review_findings: Callable[[ReviewState], dict[str, object]]
    validate_review: Callable[[ReviewState], dict[str, object]]
    recheck_affected_dimensions: Callable[[ReviewState], dict[str, object]]


class ReviewSubgraph:
    def __init__(self, *, bindings: ReviewNodeBindings | None = None, **_integration: Any) -> None:
        self._bindings = bindings

    def build(self) -> Any:
        if self._bindings is None:
            def inactive(_state: ReviewState) -> dict[str, object]:
                raise RuntimeError("review 0.9.2 semantic bindings are not runtime-active")
            bindings = ReviewNodeBindings(*(inactive for _ in range(6)))
        else:
            bindings = self._bindings
        graph = StateGraph(ReviewState)
        graph.add_node("inspect_goal_and_evidence", bindings.inspect_goal_and_evidence)
        graph.add_node("inspect_action_scope_and_route", bindings.inspect_action_scope_and_route)
        graph.add_node("inspect_constraints_and_policy_summary", bindings.inspect_constraints_and_policy_summary)
        graph.add_node("aggregate_review_findings", bindings.aggregate_review_findings)
        graph.add_node("validate_review", bindings.validate_review)
        graph.add_node("recheck_affected_dimensions", bindings.recheck_affected_dimensions)
        graph.add_edge(START, "inspect_goal_and_evidence")
        graph.add_edge("inspect_goal_and_evidence", "inspect_action_scope_and_route")
        graph.add_edge("inspect_action_scope_and_route", "inspect_constraints_and_policy_summary")
        graph.add_edge("inspect_constraints_and_policy_summary", "aggregate_review_findings")
        graph.add_edge("aggregate_review_findings", "validate_review")
        graph.add_conditional_edges(
            "validate_review",
            lambda state: "recheck" if isinstance(state.get("review_result"), dict)
            and state["review_result"].get("status") == "REVISE" else "end",
            {"recheck": "recheck_affected_dimensions", "end": END},
        )
        graph.add_edge("recheck_affected_dimensions", END)
        return graph.compile(name="review_subgraph")
