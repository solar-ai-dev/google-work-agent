from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT / "src" / "google_work_agent" / "adapters" / "langgraph" / "main"
CONDITIONAL_STAGES = frozenset(
    {
        "initialize",
        "request_understanding",
        "tool_route",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
        "single_workflow",
        "stage_one",
        "stage_two",
        "stage_three",
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
    }
)


def _composition(profile: GraphProfile, topology: tuple[str, ...]) -> WorkflowGraphComposition:
    node = object()
    return WorkflowGraphComposition(
        profile=profile,
        topology=topology,
        bindings=GraphNodeBindings(*([node] * 11)),
        control_bindings=MainControlNodeBindings(*([node] * 14)),
        should_stop_for_cancel=lambda _run_id: False,
        checkpointer=None,
    )


def test_main_conditional_stages__in_current_profiles__use_distinct_stage_owned_routers() -> None:
    profiles = {
        GraphProfile.SINGLE_BASELINE: ("single_workflow",),
        GraphProfile.THREE_STAGE: ("stage_one", "stage_two", "stage_three"),
        GraphProfile.SIX_ROLE_BASELINE: (
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ),
    }
    observed_stages: set[str] = set()
    observed_router_functions: set[object] = set()
    for profile, topology in profiles.items():
        routers = _composition(profile, topology)._stage_routers()
        observed_stages.update(routers)
        for stage, (router, successors) in routers.items():
            function = getattr(router, "func", router)
            assert function.__name__ == f"route_after_{stage}"
            assert successors
            observed_router_functions.add(function)
    assert observed_stages == CONDITIONAL_STAGES
    assert len(observed_router_functions) == len(CONDITIONAL_STAGES)


def test_main_stage_router__for_unknown_successor__fails_closed() -> None:
    for router, _successors in (
        _composition(
            GraphProfile.SIX_ROLE_BASELINE,
            (
                "request_understanding",
                "tool_route",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            ),
        )
        ._stage_routers()
        .values()
    ):
        with pytest.raises(ValueError, match="unregistered successor"):
            router(cast(Any, {"run_id": "run-1", "__target__": "unknown_target"}))


def test_main_router_modules__for_each_conditional_stage__define_exact_symbol() -> None:
    for stage in CONDITIONAL_STAGES:
        path = MAIN / "routing" / f"route_after_{stage}.py"
        assert path.is_file()
        module = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert f"route_after_{stage}" in functions


def test_main_terminal_chain__after_response_synthesis__uses_unconditional_edges() -> None:
    source = (MAIN / "graph.py").read_text(encoding="utf-8")
    assert "_route_next_node" not in source
    assert 'graph.add_edge("response_synthesis", "terminal_commit")' in source
    assert 'graph.add_edge("terminal_commit", "finalize")' in source
    assert 'graph.add_edge("finalize", END)' in source
