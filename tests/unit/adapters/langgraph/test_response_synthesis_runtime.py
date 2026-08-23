from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.response_synthesis import (
    canonicalize_answer_only_decision,
    response_synthesis_state,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
    GraphRouteTranslator,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.orchestration.contracts import (
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
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


def test_response_synthesis_materializes_completed_finalize_intent() -> None:
    state = cast(
        GraphState,
        {
            "answer_draft": _answer(),
            "__target__": "response_synthesis",
            "__logical_target__": "response_synthesis",
        },
    )

    result = response_synthesis_state(state)
    finalize_intent = cast(dict[str, object], result["finalize_intent"])

    assert result["workflow_phase"] == WorkflowPhase.RESPONSE_SYNTHESIS.value
    assert result["__target__"] == "finalize"
    assert result["__logical_target__"] == "finalize"
    assert finalize_intent["schema_version"] == 1
    assert finalize_intent["intent"] == "COMPLETED"
    assert finalize_intent["reason_code"] == "ANSWER_ONLY_RESPONSE_READY"


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
            "answer_draft": answer_draft,
            "__target__": "response_synthesis",
        },
    )

    result = response_synthesis_state(state)
    execution_summary = cast(dict[str, object], result["execution_summary"])

    assert result["workflow_phase"] == WorkflowPhase.RECOVERY.value
    assert result["__target__"] == "recovery"
    assert execution_summary["result"] == "CONTRACT_VIOLATION"


@pytest.mark.parametrize("profile", list(GraphProfile))
def test_response_synthesis_target_is_routable_for_every_profile(profile: GraphProfile) -> None:
    route = GraphRouteTranslator(profile).translate(RESPONSE_SYNTHESIS_TARGET)

    assert route.logical_target == "response_synthesis"
    assert route.node == "response_synthesis"


def test_graph_composition_has_explicit_response_synthesis_edge() -> None:
    finalize_handler = object()
    bindings = GraphNodeBindings(
        request_understanding=object(),
        tool_route=object(),
        acquisition=object(),
        context_retriever=object(),
        work_analysis=object(),
        planning=object(),
        review=object(),
        single_workflow=object(),
        domain_validation=object(),
        waiting_confirmation=object(),
        waiting_approval=object(),
        modify_review=object(),
        action_execution=object(),
        recovery=object(),
        finalize=finalize_handler,
        stage_one=object(),
        stage_two=object(),
        stage_three=object(),
    )
    composition = WorkflowGraphComposition(
        profile=GraphProfile.SIX_ROLE_BASELINE,
        topology=("planning",),
        bindings=bindings,
        route_next_node=lambda _state: "end",
        checkpointer=None,
    )

    assert bindings.for_name("response_synthesis") is finalize_handler
    assert composition.edge_map()["response_synthesis"] == "response_synthesis"
