"""Inputs shared by exact graph-profile architecture tests."""

from collections.abc import Callable
from typing import Any

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.main.state import GraphState


def profile_build_arguments() -> tuple[
    GraphNodeBindings,
    MainControlNodeBindings,
    Callable[[GraphState], str],
    Any,
    set[str],
]:
    node = object()
    bindings = GraphNodeBindings(
        request_understanding=object(),
        tool_route=object(),
        context_retriever=object(),
        work_analysis=object(),
        planning=object(),
        review=object(),
        single_workflow=object(),
        waiting_approval=object(),
        stage_one=object(),
        stage_two=object(),
        stage_three=object(),
    )
    controls = MainControlNodeBindings(
        initialize=node,
        retrieval_entry=node,
        planning_entry=node,
        review_entry=node,
        domain_validation=node,
        preflight=node,
        domain_reconcile=node,
        action_execution=node,
        verification=node,
        recovery=node,
        cancel_resolution=node,
        response_synthesis=node,
        terminal_commit=node,
        finalize=node,
    )
    return (
        bindings,
        controls,
        lambda _state: "end",
        None,
        {
            "REQUEST_UNDERSTANDING",
            "TOOL_ROUTE",
            "RETRIEVAL",
            "WORK_ANALYSIS",
            "PLANNING",
            "REVIEW",
        },
    )
