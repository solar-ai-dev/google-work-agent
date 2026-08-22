from typing import cast

from google_work_agent.adapters.langgraph.freshness_workflow import (
    _is_route_reconsideration_to_tool_route,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.orchestration.supervisor import SupervisorTarget


def test_route_reconsideration_to_tool_route_is_detected() -> None:
    state = cast(
        GraphState,
        {
            "__logical_target__": SupervisorTarget.TOOL_ROUTE.value,
            "workflow_signal": {
                "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                "reason_codes": ["NEW_RESOURCE_ROUTE_REQUIRED"],
            },
            "retrieval_result": {"coverage": "SUFFICIENT"},
        },
    )

    assert _is_route_reconsideration_to_tool_route(state) is True


def test_normal_tool_route_transition_is_not_treated_as_reconsideration() -> None:
    state = cast(
        GraphState,
        {
            "__logical_target__": SupervisorTarget.TOOL_ROUTE.value,
            "workflow_signal": None,
            "retrieval_result": {"coverage": "SUFFICIENT"},
        },
    )

    assert _is_route_reconsideration_to_tool_route(state) is False


def test_retrieval_required_signal_does_not_trigger_route_freshness_cleanup() -> None:
    state = cast(
        GraphState,
        {
            "__logical_target__": SupervisorTarget.CONTEXT_RETRIEVAL.value,
            "workflow_signal": {
                "kind": "RETRIEVAL_REQUIRED",
                "reason_codes": ["EVIDENCE_GAP"],
                "needs": [],
            },
            "retrieval_result": {"coverage": "PARTIAL"},
        },
    )

    assert _is_route_reconsideration_to_tool_route(state) is False
