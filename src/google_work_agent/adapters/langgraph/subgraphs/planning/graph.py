"""Canonical Planning owner-local LangGraph composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.assemble_plan_node import (
    assemble_plan_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.build_dependencies_node import (
    build_dependencies_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.choose_answer_or_action_from_route_node import (
    choose_answer_or_action_from_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_answer_node import (
    compose_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_arguments_per_output_route_node import (
    compose_arguments_per_output_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.draft_action_objective_per_output_route_node import (
    draft_action_objective_per_output_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.outline_answer_node import (
    outline_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.validate_plan_node import (
    validate_plan_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing.route_after_disposition import (
    route_after_disposition,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningState
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
    output_routes,
)
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    RouteArgumentResult,
)
from google_work_agent.ports.llm import StructuredLLMResult


@dataclass(frozen=True, slots=True)
class PlanningRuntimeDependencies:
    """Infrastructure-only dependencies required by canonical Planning operations."""

    invoke: PlanningSemanticInvoker


def _inactive_invoke(_prompt_id: str, _prompt_input: object) -> object:
    raise RuntimeError("planning 0.9.2 prompts are not runtime-active")


class PlanningSubgraph:
    def __init__(
        self,
        *,
        dependencies: PlanningRuntimeDependencies | None = None,
        **_integration: Any,
    ) -> None:
        self._dependencies = dependencies or PlanningRuntimeDependencies(invoke=_inactive_invoke)  # type: ignore[arg-type]

    def build(self) -> Any:
        graph = StateGraph(PlanningState)
        graph.add_node(
            "choose_answer_or_action_from_route", choose_answer_or_action_from_route_node
        )
        graph.add_node("outline_answer", outline_answer_node)
        graph.add_node(
            "compose_answer",
            partial(compose_answer_node, invoke=self._dependencies.invoke),
        )
        graph.add_node(
            "draft_action_objective_per_output_route",
            partial(
                draft_action_objective_per_output_route_node,
                invoke=self._dependencies.invoke,
            ),
        )
        graph.add_node(
            "compose_arguments_per_output_route",
            partial(
                compose_arguments_per_output_route_node,
                invoke=self._dependencies.invoke,
            ),
        )
        graph.add_node("build_dependencies", build_dependencies_node)
        graph.add_node("assemble_plan", assemble_plan_node)
        graph.add_node("validate_plan", validate_plan_node)
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
        graph.add_edge(
            "draft_action_objective_per_output_route", "compose_arguments_per_output_route"
        )
        graph.add_edge("compose_arguments_per_output_route", "build_dependencies")
        graph.add_edge("build_dependencies", "assemble_plan")
        graph.add_edge("assemble_plan", "validate_plan")
        graph.add_edge("validate_plan", END)
        return graph.compile(name="planning_subgraph")


def planning_mode_from_request_intent(
    request_intent: object,
    tool_route_plan: object | None = None,
) -> str:
    """Compatibility projection only; semantic authority is the canonical operation."""
    if isinstance(tool_route_plan, dict):
        output_plan = tool_route_plan.get("output_plan")
        if isinstance(output_plan, dict) and output_plan.get("output_mode") == "ACTION":
            return "draft_plan"
    if isinstance(request_intent, dict):
        effects = request_intent.get("requested_effect_hints")
        if isinstance(effects, list) and any(
            effect in {"CREATE", "UPDATE", "SEND", "DELETE"} for effect in effects
        ):
            return "draft_plan"
    return "answer_only"


def _real_llm_results(
    route_results: tuple[RouteArgumentResult, ...],
) -> list[StructuredLLMResult]:
    return [
        route_result.llm_result
        for route_result in route_results
        if route_result.llm_result is not None
    ]


def _frozen_output_routes(
    state: dict[str, Any],
) -> tuple[OutputToolRouteV1, ...] | None:
    plan = state.get("tool_route_plan")
    return None if plan is None else output_routes(plan)


def _frozen_read_tool_ids(state: dict[str, Any]) -> frozenset[str]:
    plan = state.get("tool_route_plan")
    if plan is None:
        return frozenset()
    return frozenset(
        tool_id
        for route in plan["input_plan"]["input_routes"]
        for tool_id in route["allowed_read_tool_ids"]
    )
