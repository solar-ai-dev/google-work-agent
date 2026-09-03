from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, initial_graph_state
from google_work_agent.adapters.langgraph.profiles.profile_registry import (
    GraphProfile,
    get_graph_profile_builder,
    get_profile_owner_bindings,
)
from google_work_agent.adapters.langgraph.subgraphs.single_workflow import (
    SingleWorkflowSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.three_stage import (
    ThreeStageOneSubgraph,
    ThreeStageTwoSubgraph,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_PROFILE_CASES = (
    (
        GraphProfile.SINGLE_BASELINE,
        "single_workflow",
        ("single_workflow",),
    ),
    (
        GraphProfile.THREE_STAGE,
        "stage_one",
        ("stage_one", "stage_two", "stage_three"),
    ),
    (
        GraphProfile.SIX_ROLE_BASELINE,
        "request_understanding",
        (
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ),
    ),
)

_CANONICAL_OWNER_BINDINGS = {
    GraphProfile.SINGLE_BASELINE: {
        "REQUEST_UNDERSTANDING": "UNIFIED_AGENT",
        "TOOL_ROUTE": "UNIFIED_AGENT",
        "RETRIEVAL": "UNIFIED_AGENT",
        "WORK_ANALYSIS": "UNIFIED_AGENT",
        "PLANNING": "UNIFIED_AGENT",
        "REVIEW": "UNIFIED_AGENT",
    },
    GraphProfile.THREE_STAGE: {
        "REQUEST_UNDERSTANDING": "STAGE_REQUEST_ROUTE_RETRIEVAL",
        "TOOL_ROUTE": "STAGE_REQUEST_ROUTE_RETRIEVAL",
        "RETRIEVAL": "STAGE_REQUEST_ROUTE_RETRIEVAL",
        "WORK_ANALYSIS": "STAGE_ANALYSIS_PLANNING",
        "PLANNING": "STAGE_ANALYSIS_PLANNING",
        "REVIEW": "STAGE_REVIEW",
    },
    GraphProfile.SIX_ROLE_BASELINE: {
        "REQUEST_UNDERSTANDING": "SIX_REQUEST_UNDERSTANDING",
        "TOOL_ROUTE": "SIX_TOOL_ROUTE",
        "RETRIEVAL": "SIX_RETRIEVAL",
        "WORK_ANALYSIS": "SIX_WORK_ANALYSIS",
        "PLANNING": "SIX_PLANNING",
        "REVIEW": "SIX_REVIEW",
    },
}


def _state(profile: GraphProfile, *, initial_target: str) -> GraphState:
    request = WorkflowStartRequest(
        run_id=f"main-component-{profile.value.lower()}",
        conversation_id="main-component-conversation",
        workflow_key=f"main-component-thread-{profile.value.lower()}",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="main graph component smoke",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("main-component-request", None, "1"),
    )
    return initial_graph_state(
        request,
        graph_profile=profile,
        graph_version="component-test",
        initial_target=initial_target,
    )


def _target_node(target: str) -> Callable[[Mapping[str, object]], dict[str, object]]:
    def node(_state: Mapping[str, object]) -> dict[str, object]:
        return {"__target__": target}

    return node


def _controls(initial_target: str) -> MainControlNodeBindings:
    def no_update(_state: Mapping[str, object]) -> dict[str, object]:
        return {}

    return MainControlNodeBindings(
        initialize=_target_node(initial_target),
        retrieval_entry=no_update,
        planning_entry=no_update,
        review_entry=no_update,
        domain_validation=no_update,
        preflight=no_update,
        domain_reconcile=no_update,
        action_execution=no_update,
        verification=no_update,
        recovery=no_update,
        cancel_resolution=no_update,
        response_synthesis=no_update,
        terminal_commit=no_update,
        finalize=no_update,
    )


def _bindings(
    physical_node: Callable[[Mapping[str, object]], dict[str, object]],
) -> GraphNodeBindings:
    return GraphNodeBindings(
        request_understanding=physical_node,
        tool_route=physical_node,
        context_retriever=physical_node,
        work_analysis=physical_node,
        planning=physical_node,
        review=physical_node,
        single_workflow=physical_node,
        waiting_approval=physical_node,
        stage_one=physical_node,
        stage_two=physical_node,
        stage_three=physical_node,
    )


def _composition(
    profile: GraphProfile,
    *,
    initial_target: str,
    physical_node: Callable[[Mapping[str, object]], dict[str, object]] | None = None,
) -> WorkflowGraphComposition:
    builder = get_graph_profile_builder(profile)
    return cast(
        WorkflowGraphComposition,
        builder(
            bindings=_bindings(physical_node or _target_node("response_synthesis")),
            control_bindings=_controls(initial_target),
            should_stop_for_cancel=lambda _run_id: False,
            checkpointer=None,
        ),
    )


@pytest.mark.parametrize(("profile", "initial_target", "topology"), _PROFILE_CASES)
def test_main_graph_profile__compiles_and_invokes__normal_path(
    profile: GraphProfile,
    initial_target: str,
    topology: tuple[str, ...],
) -> None:
    composition = _composition(profile, initial_target=initial_target)
    graph = composition.build()

    result = graph.invoke(_state(profile, initial_target=initial_target))

    assert tuple(composition.native_subgraphs()) == topology
    assert result["__target__"] == "response_synthesis"
    assert graph.get_graph().nodes.keys() >= {
        "initialize",
        "response_synthesis",
        "terminal_commit",
        "finalize",
        *topology,
    }


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_profile_owner_binding__for_every_profile__matches_canonical_map(
    profile: GraphProfile,
) -> None:
    assert dict(get_profile_owner_bindings(profile)) == _CANONICAL_OWNER_BINDINGS[profile]


def test_physical_profile_subgraphs__with_semantic_nodes__compile_and_invoke() -> None:
    semantic_node = _target_node("response_synthesis")
    cases = (
        (
            SingleWorkflowSubgraph(
                request_understanding=semantic_node,
                tool_route=semantic_node,
                retrieval=semantic_node,
                work_analysis=semantic_node,
                planning=semantic_node,
                review=semantic_node,
            ).build(),
            GraphProfile.SINGLE_BASELINE,
            "single_workflow",
            6,
        ),
        (
            ThreeStageOneSubgraph(
                request_understanding=semantic_node,
                tool_route=semantic_node,
                retrieval=semantic_node,
            ).build(),
            GraphProfile.THREE_STAGE,
            "stage_one",
            3,
        ),
        (
            ThreeStageTwoSubgraph(
                work_analysis=semantic_node,
                planning=semantic_node,
            ).build(),
            GraphProfile.THREE_STAGE,
            "stage_two",
            2,
        ),
    )

    for graph, profile, logical_target, semantic_node_count in cases:
        state = _state(profile, initial_target=logical_target)
        state["__logical_target__"] = logical_target
        result = graph.invoke(state)
        nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
        assert len(nodes) == semantic_node_count
        assert result["__target__"] == "response_synthesis"


def test_main_graph__physical_back_edge__is_bounded_and_reaches_terminal() -> None:
    visits = 0

    def physical_node(_state: Mapping[str, object]) -> dict[str, object]:
        nonlocal visits
        visits += 1
        return {
            "__target__": "single_workflow" if visits == 1 else "response_synthesis"
        }

    composition = _composition(
        GraphProfile.SINGLE_BASELINE,
        initial_target="single_workflow",
        physical_node=physical_node,
    )
    result = composition.build().invoke(
        _state(GraphProfile.SINGLE_BASELINE, initial_target="single_workflow")
    )

    assert visits == 2
    assert result["__target__"] == "response_synthesis"


def test_main_graph__unknown_successor__fails_closed() -> None:
    composition = _composition(
        GraphProfile.SIX_ROLE_BASELINE,
        initial_target="request_understanding",
        physical_node=_target_node("UNKNOWN_TARGET"),
    )

    with pytest.raises(ValueError, match="unregistered successor"):
        composition.build().invoke(
            _state(
                GraphProfile.SIX_ROLE_BASELINE,
                initial_target="request_understanding",
            )
        )
