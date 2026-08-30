"""Canonical Response Synthesis and optional-stage boundaries for SIX_ROLE.

The release runtime still contains legacy Supervisor branches that:

* send both ``ANSWER_ONLY`` and ``PLAN_READY`` through Review,
* send every successful Tool Route through Retrieval, and
* send every usable Retrieval result through Work Analysis.

Canonical Workflow v7.20 owns stricter deterministic edges. This compatibility
layer corrects those production decisions without adding LLM authority or
inventing placeholder artifacts. SIX_ROLE Work Analysis/Planning are rebuilt
with optional-input subgraphs; SINGLE/THREE experimental profiles are untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.optional_input_subgraphs import (
    CanonicalOptionalPlanningSubgraph,
    CanonicalOptionalWorkAnalysisSubgraph,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningSubgraph,
    build_production_planning_runtime,
)
from google_work_agent.application.orchestration.contracts import (
    FinalizeIntent,
    GraphStateUpdateV1,
    PlanningResult,
    WorkflowPhase,
    validate_finalize_intent_v1,
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


def response_synthesis_state(state: GraphState) -> GraphState:
    """Validate one answer and route it to the durable Finalize boundary."""

    raw_answer_value: object = state.get("answer_draft")
    if not isinstance(raw_answer_value, Mapping):
        return _response_contract_violation(state, "ANSWER_DRAFT_MISSING")
    raw_answer = cast(Mapping[str, object], raw_answer_value)
    is_v1_answer = raw_answer.get("status") == PlanningResult.ANSWER_ONLY.value
    is_v2_answer = raw_answer.get("schema_version") == 2 and isinstance(
        raw_answer.get("meta"), Mapping
    )
    if not (is_v1_answer or is_v2_answer):
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


class ResponseSynthesisMixin:
    """Canonical runtime with response synthesis and optional-stage routing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        manifest_path = cast(Path | None, kwargs.get("prompt_manifest_path"))
        super().__init__(*args, **kwargs)
        if self._graph_profile is not GraphProfile.SIX_ROLE_BASELINE:
            return

        self._analysis_subgraph = CanonicalOptionalWorkAnalysisSubgraph(
            llm_runtime=self._confirmation_llm_runtime,
            prompt_manifest_path=manifest_path,
            id_factory=self._id_factory,
            graph_profile=self._graph_profile,
            transition_run=self._transition_run,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_work_analysis_inline,
        ).build()
        action_delegate = CanonicalOptionalPlanningSubgraph(
            agent=self._planning,
            id_factory=self._id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_planning_inline,
            argument_orchestrator=self._planning_argument_orchestrator,
        ).build()
        answer_subgraph = PlanningSubgraph(
            llm_runtime=self._confirmation_llm_runtime,
            prompt_manifest_path=manifest_path,
            id_factory=self._id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_planning_inline,
        ).build()
        self._planning_subgraph = build_production_planning_runtime(
            answer=answer_subgraph,
            action_delegate=action_delegate,
        )
        self._rebuild_six_role_graph_with_optional_subgraphs()

    def _rebuild_six_role_graph_with_optional_subgraphs(self) -> None:
        self._graph_composition = WorkflowGraphComposition(
            profile=self._graph_profile,
            topology=self._topology,
            bindings=GraphNodeBindings(
                request_understanding=self._request_subgraph,
                tool_route=self._tool_route_subgraph,
                acquisition=self._acquisition_subgraph,
                context_retriever=self._context_subgraph,
                work_analysis=self._analysis_subgraph,
                planning=self._planning_subgraph,
                review=self._review_subgraph,
                single_workflow=self._single_workflow_subgraph,
                domain_validation=self._domain_validation_node,
                waiting_approval=self._waiting_approval_node,
                modify_review=self._modify_review_node,
                action_execution=self._write_execution_node,
                recovery=self._write_recovery.recover_unknown,
                finalize=self._finalize_node,
                stage_one=self._three_stage_one_subgraph,
                stage_two=self._three_stage_two_subgraph,
                stage_three=self._three_stage_review_subgraph,
            ),
            route_next_node=self._route_next_node,
            checkpointer=self._checkpointer,
        )
        self._native_agent_subgraphs = self._graph_composition.native_subgraphs()
        self._graph = self._build_graph()
        self._invocation._graph = self._graph

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        canonical_decision = canonicalize_optional_stage_decision(state, decision)
        canonical_decision = canonicalize_answer_only_decision(canonical_decision)
        return super()._merge_decision(state, update, canonical_decision)

    def _finalize_node(self, state: GraphState) -> GraphState:
        if state.get("__target__") == "response_synthesis":
            return response_synthesis_state(state)
        return super()._finalize_node(state)


__all__ = [
    "ResponseSynthesisMixin",
    "canonicalize_answer_only_decision",
    "canonicalize_optional_stage_decision",
    "response_synthesis_state",
]
