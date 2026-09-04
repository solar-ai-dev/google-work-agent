from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
    response_synthesis_node,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    GraphRouteTranslator,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
)


def _answer() -> dict[str, object]:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "answer-1", "revision": 1, "based_on": []},
        "answer": "완료된 답변",
        "evidence_refs": [],
    }


def test_response_synthesis__materializes_terminal__commit_intent() -> None:
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "planning_result": _answer(),
            "__target__": "response_synthesis",
            "__logical_target__": "response_synthesis",
        },
    )

    result = response_synthesis_node(
        state,
        read_terminal_facts=lambda _run_id: {
            "status": "PLANNING",
            "version": 4,
            "terminal_result_kind": None,
            "action_statuses": [],
            "action_effect_types": [],
        },
        build_terminal_message=BuildTerminalMessageHandler(),
    )

    assert result["workflow_phase"] == WorkflowPhase.RESPONSE_SYNTHESIS.value
    assert result["__target__"] == "terminal_commit"
    intent = cast(TerminalCommitIntentV1, result["terminal_commit_intent"])
    assert intent["kind"] == "COMPLETE_ANSWER_ONLY"
    assert intent["expected_run_version"] == 4


def test_response_synthesis__projects_verified_write_into__assistant_message() -> None:
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "run_input": {"user_request": "회의 준비 태스크를 만들어 줘"},
            "__target__": "response_synthesis",
        },
    )

    result = response_synthesis_node(
        state,
        read_terminal_facts=lambda _run_id: {
            "status": "VERIFYING",
            "version": 7,
            "terminal_result_kind": None,
            "action_statuses": ["VERIFIED"],
            "action_effect_types": ["CREATE"],
            "actions": [
                {
                    "tool_name": "tasks_create_task",
                    "effect_type": "CREATE",
                    "status": "VERIFIED",
                    "arguments": {"title": "회의 준비"},
                }
            ],
        },
        build_terminal_message=BuildTerminalMessageHandler(),
    )

    intent = cast(TerminalCommitIntentV1, result["terminal_commit_intent"])
    assert intent["kind"] == "COMPLETE_WRITE"
    assert intent["terminal_message"].result_kind == "SUCCESS"
    assert "회의 준비" in intent["terminal_message"].content
    assert "Google에서 결과를 다시 확인했습니다" in intent["terminal_message"].content
    assert "WRITE_VERIFIED" not in intent["terminal_message"].content


def test_response_synthesis__projects_read_evidence_into__assistant_message() -> None:
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "run_input": {"user_request": "선택한 메일을 요약해 줘"},
            "__target__": "response_synthesis",
        },
    )

    result = response_synthesis_node(
        state,
        read_terminal_facts=lambda _run_id: {
            "status": "EXECUTING",
            "version": 5,
            "terminal_result_kind": None,
            "action_statuses": ["VERIFIED"],
            "action_effect_types": ["READ"],
            "actions": [
                {
                    "tool_name": "gmail_get_thread",
                    "effect_type": "READ",
                    "status": "VERIFIED",
                    "arguments": {"thread_id": "thread-project"},
                    "evidence_excerpts": ["목요일 회고 초안이 필요합니다."],
                }
            ],
        },
        build_terminal_message=BuildTerminalMessageHandler(),
    )

    intent = cast(TerminalCommitIntentV1, result["terminal_commit_intent"])
    assert intent["kind"] == "COMPLETE_READ_ONLY"
    assert "목요일 회고 초안이 필요합니다" in intent["terminal_message"].content


@pytest.mark.parametrize(
    "planning_result",
    [None, {"actions": []}, {"schema_version": 2, "answer": ""}],
)
def test_response_synthesis__fails_closed__on_invalid_answer(planning_result: object) -> None:
    state = cast(GraphState, {"run_id": "run-1", "planning_result": planning_result})

    with pytest.raises(ValueError, match="authorize terminal synthesis"):
        response_synthesis_node(
            state,
            read_terminal_facts=lambda _run_id: {
                "status": "PLANNING",
                "version": 4,
                "terminal_result_kind": None,
                "action_statuses": [],
                "action_effect_types": [],
            },
            build_terminal_message=BuildTerminalMessageHandler(),
        )


@pytest.mark.parametrize("profile", list(GraphProfile))
def test_response_synthesis__target_is_routable__for_every_profile(profile: GraphProfile) -> None:
    route = GraphRouteTranslator(profile).translate(SupervisorTarget.RESPONSE_SYNTHESIS.value)

    assert route.logical_target == "response_synthesis"
    assert route.node == "response_synthesis"
