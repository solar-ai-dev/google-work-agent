from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    response_synthesis_node,
)
from google_work_agent.adapters.langgraph.main.response_synthesis import (
    canonicalize_answer_only_decision,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
    GraphRouteTranslator,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.agents.planning.contracts.planning_result import (
    ActionPlanDraftV1,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
)


def _answer() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "ANSWER_ONLY",
        "answer": "완료된 답변",
        "evidence_refs": [],
        "resource_refs": [],
        "reason_codes": [],
        "confirmation": None,
        "blockers": [],
    }


def _answer_review_decision() -> SupervisorDecisionV1:
    return {
        "target": SupervisorTarget.PLAN_REVIEW_INSPECT.value,
        "next_phase": WorkflowPhase.PLAN_REVIEW.value,
        "state_update": cast(
            GraphStateUpdateV1,
            {
                "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
                "user_interrupt": None,
                "finalize_intent": None,
                "answer_draft": _answer(),
                "plan_draft": None,
            },
        ),
        "reason_code": "ANSWER_ONLY",
        "budget_decision": None,
    }


def test_answer_only_review_decision_is_rewritten_to_response_synthesis() -> None:
    decision = canonicalize_answer_only_decision(_answer_review_decision())

    assert decision["target"] == RESPONSE_SYNTHESIS_TARGET
    assert decision["next_phase"] == WorkflowPhase.RESPONSE_SYNTHESIS.value
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.RESPONSE_SYNTHESIS.value
    assert decision["state_update"]["answer_draft"] == _answer()
    assert decision["state_update"]["plan_draft"] is None
    assert decision["state_update"]["plan_review"] is None


def test_plan_ready_review_decision_is_not_rewritten() -> None:
    decision = _answer_review_decision()
    decision["state_update"]["answer_draft"] = None
    decision["state_update"]["plan_draft"] = cast(
        ActionPlanDraftV1,
        {"schema_version": 2, "status": "PLAN_READY"},
    )
    decision["reason_code"] = "PLAN_READY"

    assert canonicalize_answer_only_decision(decision) is decision
    assert decision["target"] == SupervisorTarget.PLAN_REVIEW_INSPECT.value


def test_response_synthesis_materializes_terminal_commit_intent() -> None:
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "answer_draft": _answer(),
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
    terminal_intent = cast(dict[str, object], result["terminal_commit_intent"])

    assert result["workflow_phase"] == WorkflowPhase.RESPONSE_SYNTHESIS.value
    assert result["__target__"] == "terminal_commit"
    assert result["__logical_target__"] == "terminal_commit"
    assert terminal_intent["schema_version"] == 1
    assert terminal_intent["kind"] == "COMPLETE_ANSWER_ONLY"
    assert terminal_intent["expected_run_version"] == 4


@pytest.mark.parametrize(
    "answer_draft",
    [
        None,
        {"status": "PLAN_READY", "answer": "wrong"},
        {"status": "ANSWER_ONLY", "answer": ""},
    ],
)
def test_response_synthesis_fails_closed_on_invalid_answer(answer_draft: object) -> None:
    state = cast(
        GraphState,
        {
            "run_id": "run-1",
            "answer_draft": answer_draft,
            "__target__": "response_synthesis",
        },
    )

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


def test_graph_composition_has_explicit_response_synthesis_edge() -> None:
    response_handler = object()
    terminal_handler = object()
    finalize_handler = object()
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
    composition = WorkflowGraphComposition(
        profile=GraphProfile.SIX_ROLE_BASELINE,
        topology=("planning",),
        bindings=bindings,
        control_bindings=MainControlNodeBindings(
            initialize=object(),
            retrieval_entry=object(),
            planning_entry=object(),
            review_entry=object(),
            domain_validation=object(),
            preflight=object(),
            domain_reconcile=object(),
            action_execution=object(),
            verification=object(),
            recovery=object(),
            cancel_resolution=object(),
            response_synthesis=response_handler,
            terminal_commit=terminal_handler,
            finalize=finalize_handler,
        ),
        route_next_node=lambda _state: "end",
        checkpointer=None,
    )

    assert composition.node_handler("response_synthesis") is response_handler
    assert composition.node_handler("terminal_commit") is terminal_handler
    assert composition.node_handler("finalize") is finalize_handler
    assert len({id(response_handler), id(terminal_handler), id(finalize_handler)}) == 3
    assert composition.edge_map()["response_synthesis"] == "response_synthesis"
    assert composition.edge_map()["terminal_commit"] == "terminal_commit"
