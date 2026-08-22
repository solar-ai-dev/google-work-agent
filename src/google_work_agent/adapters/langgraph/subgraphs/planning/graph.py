"""Canonical Planning owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.assemble_plan_node import assemble_plan_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.build_dependencies_node import build_dependencies_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.choose_answer_or_action_from_route_node import choose_answer_or_action_from_route_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_answer_node import compose_answer_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_arguments_per_output_route_node import compose_arguments_per_output_route_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.draft_action_objective_per_output_route_node import draft_action_objective_per_output_route_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.outline_answer_node import outline_answer_node
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.validate_plan_node import validate_plan_node
from google_work_agent.adapters.langgraph.subgraphs.planning.routing.route_after_disposition import route_after_disposition
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningState


@dataclass(frozen=True, slots=True)
class PlanningNodeBindings:
    """Application operations injected into canonical thin node modules."""

    choose_answer_or_action_from_route: Callable[[object], object]
    outline_answer: Callable[[object], object]
    compose_answer: Callable[[object], object]
    draft_action_objective_per_output_route: Callable[[object], object]
    compose_arguments_per_output_route: Callable[[object], object]
    build_dependencies: Callable[[object], object]
    assemble_plan: Callable[[object], object]
    validate_plan: Callable[[object], object]


class PlanningSubgraph:
    def __init__(self, *, bindings: PlanningNodeBindings | None = None, **_integration: Any) -> None:
        self._bindings = bindings

    def build(self) -> Any:
        if self._bindings is None:
            def inactive(_value: object) -> object:
                raise RuntimeError("planning 0.9.2 semantic operations are not runtime-active")
            bindings = PlanningNodeBindings(*(inactive for _ in range(8)))
        else:
            bindings = self._bindings

        graph = StateGraph(PlanningState)
        graph.add_node("choose_answer_or_action_from_route", partial(choose_answer_or_action_from_route_node, operation=bindings.choose_answer_or_action_from_route))
        graph.add_node("outline_answer", partial(outline_answer_node, operation=bindings.outline_answer))
        graph.add_node("compose_answer", partial(compose_answer_node, operation=bindings.compose_answer))
        graph.add_node("draft_action_objective_per_output_route", partial(draft_action_objective_per_output_route_node, operation=bindings.draft_action_objective_per_output_route))
        graph.add_node("compose_arguments_per_output_route", partial(compose_arguments_per_output_route_node, operation=bindings.compose_arguments_per_output_route))
        graph.add_node("build_dependencies", partial(build_dependencies_node, operation=bindings.build_dependencies))
        graph.add_node("assemble_plan", partial(assemble_plan_node, operation=bindings.assemble_plan))
        graph.add_node("validate_plan", partial(validate_plan_node, operation=bindings.validate_plan))
        graph.add_edge(START, "choose_answer_or_action_from_route")
        graph.add_conditional_edges(
            "choose_answer_or_action_from_route",
            route_after_disposition,
            {
                "outline_answer": "outline_answer",
                "draft_action_objective_per_output_route": "draft_action_objective_per_output_route",
            },
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
