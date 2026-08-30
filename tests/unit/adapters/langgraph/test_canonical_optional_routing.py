from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.response_synthesis import (
    canonicalize_optional_stage_decision,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.orchestration.contracts import (
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
)


def _state(
    *, analysis_requirement: str, output_mode: str, input_routes: list[object]
) -> GraphState:
    return cast(
        GraphState,
        {
            "request_intent": {
                "schema_version": 2,
                "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
                "goal": "goal",
                "completion_conditions": [],
                "constraints": [],
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": analysis_requirement,
                "ambiguity": {
                    "requires_confirmation": False,
                    "reason_codes": [],
                    "missing_fields": [],
                },
            },
            "tool_route_plan": {
                "schema_version": 2,
                "registry_version": "registry-1",
                "input_plan": {
                    "schema_version": 1,
                    "meta": {"artifact_id": "input-1", "revision": 1, "based_on": []},
                    "input_routes": input_routes,
                },
                "output_plan": {
                    "schema_version": 1,
                    "meta": {"artifact_id": "output-1", "revision": 1, "based_on": []},
                    "output_mode": output_mode,
                    "output_routes": [],
                },
            },
        },
    )


def _decision(*, target: str, reason_code: str) -> SupervisorDecisionV1:
    phase = (
        WorkflowPhase.CONTEXT_RETRIEVAL.value
        if target == SupervisorTarget.CONTEXT_RETRIEVAL.value
        else WorkflowPhase.WORK_ANALYSIS.value
    )
    return {
        "target": target,
        "next_phase": phase,
        "state_update": cast(GraphStateUpdateV1, {"workflow_phase": phase}),
        "reason_code": reason_code,
        "budget_decision": None,
    }


def test_tool_route_with_input_route_stays_retrieval() -> None:
    state = _state(
        analysis_requirement="NONE",
        output_mode="ANSWER",
        input_routes=[{"route_id": "in-1"}],
    )
    decision = _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL.value,
        reason_code="ROUTE_READY",
    )

    assert canonicalize_optional_stage_decision(state, decision) == decision


def test_answer_without_input_or_analysis_routes_directly_to_planning() -> None:
    state = _state(analysis_requirement="NONE", output_mode="ANSWER", input_routes=[])
    decision = _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL.value,
        reason_code="NO_TOOL_NEEDED",
    )

    result = canonicalize_optional_stage_decision(state, decision)

    assert result["target"] == SupervisorTarget.SOLUTION_PLANNING.value
    assert result["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert result["state_update"]["retrieval_result"] is None
    assert result["state_update"]["work_analysis_result"] is None


def test_no_input_with_required_analysis_routes_to_work_analysis() -> None:
    state = _state(analysis_requirement="REQUIRED", output_mode="ANSWER", input_routes=[])
    decision = _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL.value,
        reason_code="NO_TOOL_NEEDED",
    )

    result = canonicalize_optional_stage_decision(state, decision)

    assert result["target"] == SupervisorTarget.WORK_ANALYSIS.value
    assert result["next_phase"] == WorkflowPhase.WORK_ANALYSIS.value


def test_action_without_input_does_not_invent_retrieval_skip() -> None:
    state = _state(analysis_requirement="NONE", output_mode="ACTION", input_routes=[])
    decision = _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL.value,
        reason_code="ROUTE_READY",
    )

    assert canonicalize_optional_stage_decision(state, decision) == decision


def test_retrieval_answer_with_no_analysis_routes_to_planning() -> None:
    state = _state(
        analysis_requirement="NONE",
        output_mode="ANSWER",
        input_routes=[{"route_id": "in-1"}],
    )
    decision = _decision(
        target=SupervisorTarget.WORK_ANALYSIS.value,
        reason_code="SUFFICIENT",
    )

    result = canonicalize_optional_stage_decision(state, decision)

    assert result["target"] == SupervisorTarget.SOLUTION_PLANNING.value
    assert result["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert result["state_update"]["work_analysis_result"] is None


def test_retrieval_with_required_analysis_stays_work_analysis() -> None:
    state = _state(
        analysis_requirement="REQUIRED",
        output_mode="ANSWER",
        input_routes=[{"route_id": "in-1"}],
    )
    decision = _decision(
        target=SupervisorTarget.WORK_ANALYSIS.value,
        reason_code="PARTIAL",
    )

    assert canonicalize_optional_stage_decision(state, decision) == decision


def test_invalid_analysis_requirement_fails_closed() -> None:
    state = _state(analysis_requirement="UNKNOWN", output_mode="ANSWER", input_routes=[])
    decision = _decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL.value,
        reason_code="NO_TOOL_NEEDED",
    )

    with pytest.raises(ValueError, match="analysis_requirement"):
        canonicalize_optional_stage_decision(state, decision)
