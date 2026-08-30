"""Inputs shared by exact graph-profile architecture tests."""

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)


def profile_build_arguments() -> dict[str, object]:
    node = object()
    bindings = GraphNodeBindings(
        request_understanding=object(),
        tool_route=object(),
        acquisition=object(),
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
    return {
        "bindings": bindings,
        "control_bindings": controls,
        "route_next_node": lambda _state: "end",
        "checkpointer": None,
        "semantic_owners": {
            "REQUEST_UNDERSTANDING",
            "TOOL_ROUTE",
            "RETRIEVAL",
            "WORK_ANALYSIS",
            "PLANNING",
            "REVIEW",
        },
    }
