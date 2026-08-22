"""Canonical Planning owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningState


@dataclass(frozen=True, slots=True)
class PlanningNodeBindings:
    choose_answer_or_action_from_route: Callable[[PlanningState], dict[str, object]]
    outline_answer: Callable[[PlanningState], dict[str, object]]
    compose_answer: Callable[[PlanningState], dict[str, object]]
    draft_action_objective_per_output_route: Callable[[PlanningState], dict[str, object]]
    compose_arguments_per_output_route: Callable[[PlanningState], dict[str, object]]
    build_dependencies: Callable[[PlanningState], dict[str, object]]
    assemble_plan: Callable[[PlanningState], dict[str, object]]
    validate_plan: Callable[[PlanningState], dict[str, object]]


class PlanningSubgraph:
    """Compile only thin owner-local nodes; semantic dependencies are injected by composition."""

    def __init__(self, *, bindings: PlanningNodeBindings | None = None, **_integration: Any) -> None:
        self._bindings = bindings

    def build(self) -> Any:
        if self._bindings is None:
            def inactive(_state: PlanningState) -> dict[str, object]:
                raise RuntimeError("planning 0.9.2 semantic bindings are not runtime-active")
            bindings = PlanningNodeBindings(*(inactive for _ in range(8)))
        else:
            bindings = self._bindings
        graph = StateGraph(PlanningState)
        graph.add_node("choose_answer_or_action_from_route", bindings.choose_answer_or_action_from_route)
        graph.add_node("outline_answer", bindings.outline_answer)
        graph.add_node("compose_answer", bindings.compose_answer)
        graph.add_node("draft_action_objective_per_output_route", bindings.draft_action_objective_per_output_route)
        graph.add_node("compose_arguments_per_output_route", bindings.compose_arguments_per_output_route)
        graph.add_node("build_dependencies", bindings.build_dependencies)
        graph.add_node("assemble_plan", bindings.assemble_plan)
        graph.add_node("validate_plan", bindings.validate_plan)
        graph.add_edge(START, "choose_answer_or_action_from_route")
        graph.add_conditional_edges(
            "choose_answer_or_action_from_route",
            lambda state: "answer" if state.get("planning_disposition") == "ANSWER" else "action",
            {"answer": "outline_answer", "action": "draft_action_objective_per_output_route"},
        )
        graph.add_edge("outline_answer", "compose_answer")
        graph.add_edge("compose_answer", END)
        graph.add_edge("draft_action_objective_per_output_route", "compose_arguments_per_output_route")
        graph.add_edge("compose_arguments_per_output_route", "build_dependencies")
        graph.add_edge("build_dependencies", "assemble_plan")
        graph.add_edge("assemble_plan", "validate_plan")
        graph.add_edge("validate_plan", END)
        return graph.compile(name="planning_subgraph")


def planning_mode_from_request_intent(
    request_intent: object,
    tool_route_plan: object | None = None,
) -> str:
    """Compatibility projection only; semantic authority is choose_answer_or_action_from_route."""
    if isinstance(tool_route_plan, dict):
        output_plan = tool_route_plan.get("output_plan")
        if isinstance(output_plan, dict) and output_plan.get("output_mode") == "ACTION":
            return "draft_plan"
    return "answer_only"
