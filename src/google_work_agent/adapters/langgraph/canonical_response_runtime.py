"""Canonical Response Synthesis boundary for ANSWER_ONLY Planning results.

The release runtime still contains a legacy Supervisor branch that sends both
``ANSWER_ONLY`` and ``PLAN_READY`` through Review. Canonical Workflow v7.20
owns a stricter edge: ``Planning.ANSWER_ONLY -> RESPONSE_SYNTHESIS`` while
only ``PLAN_READY`` enters Review.

This compatibility layer corrects the production decision at the runtime
boundary without adding another LLM call or changing Planning output. The
Response Synthesis node validates the already-produced answer, materializes a
code-owned ``FinalizeIntent(COMPLETED)``, and then delegates durable assistant
message persistence / Run completion to the existing Finalize boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    LangGraphWorkflowRuntime as _CanonicalPlanningRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.route_translation import (
    RESPONSE_SYNTHESIS_TARGET,
)
from google_work_agent.application.workflows import (
    FinalizeIntent,
    GraphStateUpdateV1,
    PlanningResult,
    SupervisorDecisionV1,
    SupervisorTarget,
    WorkflowPhase,
    validate_finalize_intent_v1,
)

_REVIEW_TARGETS = frozenset(
    {
        SupervisorTarget.PLAN_REVIEW_INSPECT.value,
        SupervisorTarget.PLAN_REVIEW_RECHECK.value,
    }
)


def canonicalize_answer_only_decision(
    decision: SupervisorDecisionV1,
) -> SupervisorDecisionV1:
    """Rewrite only the legacy ANSWER_ONLY-to-Review edge.

    PLAN_READY and every non-Planning decision pass through byte-for-byte.
    A stale Review result is cleared when an old checkpoint resumes through
    the compatibility path so it cannot remain a second routing authority.
    """

    if decision["target"] not in _REVIEW_TARGETS:
        return decision
    state_update = dict(decision["state_update"])
    raw_answer = state_update.get("answer_draft")
    if not isinstance(raw_answer, Mapping):
        return decision
    if raw_answer.get("status") != PlanningResult.ANSWER_ONLY.value:
        return decision

    state_update["workflow_phase"] = WorkflowPhase.RESPONSE_SYNTHESIS.value
    state_update["plan_review"] = None
    state_update["finalize_intent"] = None
    return {
        **decision,
        "target": RESPONSE_SYNTHESIS_TARGET,
        "next_phase": WorkflowPhase.RESPONSE_SYNTHESIS.value,
        "state_update": cast(GraphStateUpdateV1, state_update),
        "reason_code": "ANSWER_ONLY_RESPONSE_READY",
    }


def response_synthesis_state(state: GraphState) -> GraphState:
    """Validate one answer and route it to the durable Finalize boundary."""

    raw_answer = state.get("answer_draft")
    if not isinstance(raw_answer, Mapping):
        return _response_contract_violation(state, "ANSWER_DRAFT_MISSING")
    if raw_answer.get("status") != PlanningResult.ANSWER_ONLY.value:
        return _response_contract_violation(state, "ANSWER_DRAFT_STATUS_INVALID")
    answer = raw_answer.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _response_contract_violation(state, "ANSWER_TEXT_MISSING")

    return {
        **state,
        "__logical_target__": "finalize",
        "__target__": "finalize",
        "workflow_phase": WorkflowPhase.RESPONSE_SYNTHESIS.value,
        "finalize_intent": validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.COMPLETED.value,
                "reason_code": "ANSWER_ONLY_RESPONSE_READY",
            }
        ),
    }


def _response_contract_violation(state: GraphState, reason_code: str) -> GraphState:
    return {
        **state,
        "__logical_target__": "recovery",
        "__target__": "recovery",
        "workflow_phase": WorkflowPhase.RECOVERY.value,
        "execution_summary": {
            "result": "CONTRACT_VIOLATION",
            "reason_code": reason_code,
        },
    }


class LangGraphWorkflowRuntime(_CanonicalPlanningRuntime):
    """Canonical runtime with explicit deterministic Response Synthesis."""

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        return super()._merge_decision(
            state,
            update,
            canonicalize_answer_only_decision(decision),
        )

    def _finalize_node(self, state: GraphState) -> GraphState:
        if state.get("__target__") == "response_synthesis":
            return response_synthesis_state(state)
        return super()._finalize_node(state)


__all__ = [
    "LangGraphWorkflowRuntime",
    "canonicalize_answer_only_decision",
    "response_synthesis_state",
]
