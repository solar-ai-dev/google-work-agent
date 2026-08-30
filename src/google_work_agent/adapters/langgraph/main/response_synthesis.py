"""Canonical Response Synthesis and optional-stage routing boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.orchestration.contracts import (
    GraphStateUpdateV1,
    PlanningResult,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
)

_REVIEW_TARGETS = frozenset(
    {
        SupervisorTarget.PLAN_REVIEW_INSPECT.value,
        SupervisorTarget.PLAN_REVIEW_RECHECK.value,
    }
)
_RETRIEVAL_SUCCESS_REASONS = frozenset({"SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"})
_TOOL_ROUTE_SUCCESS_REASONS = frozenset({"ROUTE_READY", "NO_TOOL_NEEDED"})


def canonicalize_answer_only_decision(
    decision: SupervisorDecisionV1,
) -> SupervisorDecisionV1:
    """Rewrite only the legacy ANSWER_ONLY-to-Review edge."""

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


def canonicalize_optional_stage_decision(
    state: GraphState,
    decision: SupervisorDecisionV1,
) -> SupervisorDecisionV1:
    """Apply Canonical ToolRoute/Retrieval skip edges deterministically.

    Only already-frozen typed facts are consulted:
    ``ToolRoutePlanV2.input_plan.input_routes``, its frozen ``output_mode``, and
    ``RequestIntentV2.analysis_requirement``. No natural-language field,
    missing-information string, tool prefix, or provider name is interpreted.
    """

    target = decision["target"]
    reason_code = decision.get("reason_code")
    state_update = dict(decision["state_update"])

    if (
        target == SupervisorTarget.CONTEXT_RETRIEVAL.value
        and reason_code in _TOOL_ROUTE_SUCCESS_REASONS
    ):
        raw_plan = state_update.get("tool_route_plan", state.get("tool_route_plan"))
        input_routes = _input_routes(raw_plan)
        if input_routes:
            return decision
        output_mode = _output_mode(raw_plan)
        analysis_requirement = _analysis_requirement(state)
        if output_mode == "ANSWER" and analysis_requirement == "NONE":
            next_target = SupervisorTarget.SOLUTION_PLANNING
            next_phase = WorkflowPhase.SOLUTION_PLANNING
        elif analysis_requirement == "REQUIRED":
            next_target = SupervisorTarget.WORK_ANALYSIS
            next_phase = WorkflowPhase.WORK_ANALYSIS
        else:
            return decision
        state_update.update(
            {
                "workflow_phase": next_phase.value,
                "retrieval_result": None,
                "context_result": None,
                "work_analysis_result": None,
                "answer_draft": None,
                "plan_draft": None,
                "plan_review": None,
            }
        )
        return {
            **decision,
            "target": next_target.value,
            "next_phase": next_phase.value,
            "state_update": cast(GraphStateUpdateV1, state_update),
        }

    if (
        target == SupervisorTarget.WORK_ANALYSIS.value
        and reason_code in _RETRIEVAL_SUCCESS_REASONS
        and _analysis_requirement(state) == "NONE"
    ):
        raw_plan = state.get("tool_route_plan")
        if _output_mode(raw_plan) != "ANSWER":
            return decision
        state_update.update(
            {
                "workflow_phase": WorkflowPhase.SOLUTION_PLANNING.value,
                "work_analysis_result": None,
                "answer_draft": None,
                "plan_draft": None,
                "plan_review": None,
            }
        )
        return {
            **decision,
            "target": SupervisorTarget.SOLUTION_PLANNING.value,
            "next_phase": WorkflowPhase.SOLUTION_PLANNING.value,
            "state_update": cast(GraphStateUpdateV1, state_update),
        }

    return decision


def _input_routes(raw_plan: object) -> list[object]:
    if not isinstance(raw_plan, Mapping):
        raise ValueError("canonical routing requires frozen tool_route_plan")
    raw_input_plan = raw_plan.get("input_plan")
    if not isinstance(raw_input_plan, Mapping):
        raise ValueError("canonical routing requires input_plan")
    raw_routes = raw_input_plan.get("input_routes")
    if not isinstance(raw_routes, list):
        raise ValueError("canonical routing requires input_plan.input_routes")
    return list(raw_routes)


def _output_mode(raw_plan: object) -> str:
    if not isinstance(raw_plan, Mapping):
        raise ValueError("canonical routing requires frozen tool_route_plan")
    raw_output_plan = raw_plan.get("output_plan")
    if not isinstance(raw_output_plan, Mapping):
        raise ValueError("canonical routing requires output_plan")
    output_mode = raw_output_plan.get("output_mode")
    if output_mode not in {"ANSWER", "ACTION"}:
        raise ValueError("canonical routing requires a valid output_mode")
    return cast(str, output_mode)


def _analysis_requirement(state: GraphState) -> str:
    raw_intent = state.get("request_intent")
    if not isinstance(raw_intent, Mapping):
        raise ValueError("canonical routing requires request_intent")
    requirement = raw_intent.get("analysis_requirement")
    if requirement not in {"NONE", "REQUIRED"}:
        raise ValueError("request_intent.analysis_requirement is invalid")
    return cast(str, requirement)


class ResponseSynthesisMixin:
    """Canonical runtime with response synthesis and optional-stage routing."""

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        canonical_decision = canonicalize_optional_stage_decision(state, decision)
        canonical_decision = canonicalize_answer_only_decision(canonical_decision)
        return super()._merge_decision(state, update, canonical_decision)

__all__ = [
    "ResponseSynthesisMixin",
    "canonicalize_answer_only_decision",
    "canonicalize_optional_stage_decision",
]
