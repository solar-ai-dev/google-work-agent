from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor import (
    PlanningRouteResultV1,
    WorkAnalysisRouteResultV1,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget


def test_work_analysis__complete_disposition__routes_to_planning() -> None:
    state = _state(analysis_requirement="REQUIRED", with_retrieval=True)
    analysis = {
        "schema_version": 2,
        "meta": {
            "artifact_id": "analysis-1",
            "revision": 1,
            "based_on": [
                {"artifact_id": "intent-1", "revision": 1},
                {"artifact_id": "input-1", "revision": 1},
                {"artifact_id": "output-1", "revision": 1},
                {"artifact_id": "retrieval-1", "revision": 1},
            ],
        },
    }

    decision = route_supervisor(
        phase=WorkflowPhase.WORK_ANALYSIS,
        state=state,
        result=cast(
            WorkAnalysisRouteResultV1,
            {
                "disposition": "COMPLETE",
                "typed_result": analysis,
                "workflow_signal": None,
                "reason_codes": [],
            },
        ),
    )

    assert decision["target"] == SupervisorTarget.SOLUTION_PLANNING.value
    assert decision["state_update"]["work_analysis_result"] == analysis


def test_retrieval_answer__with_no_analysis__routes_to_planning() -> None:
    state = _state(analysis_requirement="NONE", with_retrieval=False)
    answer = {
        "schema_version": 2,
        "meta": {
            "artifact_id": "answer-1",
            "revision": 1,
            "based_on": [{"artifact_id": "output-1", "revision": 1}],
        },
        "answer": "완료했습니다.",
        "evidence_refs": [],
    }

    decision = route_supervisor(
        phase=WorkflowPhase.SOLUTION_PLANNING,
        state=state,
        result=cast(
            PlanningRouteResultV1,
            {
                "disposition": "ANSWER_ONLY",
                "typed_result": answer,
                "reason_codes": [],
            },
        ),
    )

    assert decision["target"] == SupervisorTarget.RESPONSE_SYNTHESIS.value
    assert decision["state_update"]["planning_result"] == answer


def _state(*, analysis_requirement: str, with_retrieval: bool) -> GraphState:
    request_ref = {"artifact_id": "intent-1", "revision": 1}
    input_ref = {"artifact_id": "input-1", "revision": 1}
    return cast(
        GraphState,
        {
            "run_id": "run-1",
            "workflow_phase": WorkflowPhase.WORK_ANALYSIS.value,
            "request_intent": {
                "schema_version": 2,
                "meta": {**request_ref, "based_on": []},
                "goal": "요청",
                "analysis_requirement": analysis_requirement,
            },
            "tool_route_plan": {
                "schema_version": 2,
                "input_plan": {
                    "schema_version": 1,
                    "meta": {**input_ref, "based_on": [request_ref]},
                    "input_routes": [{"route_id": "route-1"}] if with_retrieval else [],
                },
                "output_plan": {
                    "schema_version": 1,
                    "meta": {
                        "artifact_id": "output-1",
                        "revision": 1,
                        "based_on": [request_ref],
                    },
                    "output_mode": "ANSWER",
                },
            },
            "retrieval_result": (
                {
                    "schema_version": 1,
                    "meta": {
                        "artifact_id": "retrieval-1",
                        "revision": 1,
                        "based_on": [request_ref, input_ref],
                    },
                }
                if with_retrieval
                else None
            ),
            "work_analysis_result": None,
            "planning_result": None,
            "plan_review": None,
            "retry_budget": build_default_run_budget(),
            "trace_context": {},
        },
    )
