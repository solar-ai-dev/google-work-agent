from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
    response_synthesis_node,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
    GraphRouteTranslator,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
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


def test_response_synthesis_materializes_terminal_commit_intent() -> None:
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


@pytest.mark.parametrize(
    "planning_result",
    [None, {"actions": []}, {"schema_version": 2, "answer": ""}],
)
def test_response_synthesis_fails_closed_on_invalid_answer(planning_result: object) -> None:
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
def test_response_synthesis_target_is_routable_for_every_profile(profile: GraphProfile) -> None:
    route = GraphRouteTranslator(profile).translate(RESPONSE_SYNTHESIS_TARGET)

    assert route.logical_target == "response_synthesis"
    assert route.node == "response_synthesis"
