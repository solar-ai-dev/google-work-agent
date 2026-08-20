"""SIX_ROLE subgraphs that preserve Canonical optional upstream artifacts.

Workflow v7.20 allows two paths the legacy release subgraphs could not execute:

* Tool Route may enter Work Analysis without Retrieval when analysis is required
  but no frozen input route exists.
* Planning may run without Work Analysis when analysis is not required, and
  may run after no-Retrieval Work Analysis without fabricating RetrievalResult.

These subclasses change only those optional-input boundaries. They never
materialize fake Retrieval/Analysis artifacts and delegate fully-populated
legacy paths back to the existing production subgraphs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.graph_state import (
    ANALYSIS_AGENT_LOCAL_KEY,
    PLANNING_AGENT_LOCAL_KEY,
    PLANNING_MODE_KEY,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    PlanningLocalState,
    WorkAnalysisLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.planning import (
    PlanningSubgraph,
    _frozen_output_routes,
    _frozen_read_tool_ids,
    _real_llm_results,
    planning_mode_from_request_intent,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis import WorkAnalysisSubgraph
from google_work_agent.application.workflows import (
    ActionPlanDraftV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    ConfirmationResponseV1,
    EvidenceDraftV1,
    GraphStateUpdateV1,
    ReviewIssueV1,
    SupervisorDecisionV1,
    WorkAnalysisResultV1,
    WorkflowPhase,
    route_supervisor,
)
from google_work_agent.application.workflows.canonical_optional_inputs import (
    CanonicalOptionalInputPlanningAgent,
    CanonicalOptionalInputWorkAnalysisAgent,
    assemble_plan_with_optional_analysis,
    validate_answer_with_optional_analysis,
    validate_plan_with_optional_analysis,
)
from google_work_agent.application.workflows.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.ports import StructuredLLMResult


class CanonicalOptionalWorkAnalysisSubgraph(WorkAnalysisSubgraph):
    """Work Analysis that accepts the Canonical no-Retrieval entry path."""

    def _init_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        invocation_id = self._id_factory()
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        local_state = build_agent_local_state(
            agent_role="work_analysis",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": request_intent,
                "retrieval_result": state.get("retrieval_result"),
            },
            prompt_ref=self._agent.analyze_prompt_ref,
        )
        return {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=invocation_id,
                subgraph_namespace="analysis",
                node_name="init",
                prompt_ref=self._agent.analyze_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _run_analyze_attempt(
        self,
        state: WorkAnalysisLocalState,
        *,
        confirmation_response: ConfirmationResponseV1 | None,
    ) -> tuple[WorkAnalysisResultV1, StructuredLLMResult]:
        retrieval_result = state.get("retrieval_result")
        if retrieval_result is not None:
            return super()._run_analyze_attempt(
                state, confirmation_response=confirmation_response
            )
        if not isinstance(self._agent, CanonicalOptionalInputWorkAnalysisAgent):
            raise TypeError("optional Work Analysis requires canonical optional-input agent")

        receipt_refs: list[str] = []
        for receipt in state.get("policy_confirmation_receipts", []):
            if not isinstance(receipt, Mapping):
                continue
            receipt_id = receipt.get("confirmation_receipt_id")
            if isinstance(receipt_id, str) and receipt_id:
                receipt_refs.append(receipt_id)

        ensure_llm_call_budget(state)
        llm_result = self._agent.invoke_without_retrieval(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            request=request_from_state(state),
            policy_confirmation_receipt_refs=receipt_refs,
            confirmation_response=confirmation_response,
        )
        return self._agent.build_without_retrieval(llm_result), llm_result


class CanonicalOptionalPlanningSubgraph(PlanningSubgraph):
    """Planning that accepts Canonical optional Retrieval/Work Analysis inputs."""

    def _init_node(self, state: PlanningLocalState) -> PlanningLocalState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        tool_route_plan = state.get("tool_route_plan")
        mode = planning_mode_from_request_intent(request_intent, tool_route_plan)
        if review is not None and review.get("status") == "REVISE":
            mode = "revise_answer" if state.get("answer_draft") is not None else "revise_plan"
        prompt_ref = {
            "answer_only": self._agent.answer_only_prompt_ref,
            "draft_plan": self._argument_orchestrator.prompt_ref,
            "revise_answer": self._agent.revise_answer_prompt_ref,
            "revise_plan": self._argument_orchestrator.revise_prompt_ref,
        }[mode]
        local_state = build_agent_local_state(
            agent_role="planning",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": request_intent,
                "analysis_result": state.get("analysis_result"),
                "retrieval_result": state.get("retrieval_result"),
                "mode": mode,
                "output_routes": list(_frozen_output_routes(state) or ()),
            },
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: local_state,
            PLANNING_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=invocation_id,
                subgraph_namespace="planning",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
                revision_increment=1 if mode.startswith("revise") else 0,
            ),
        }

    def _evidence_drafts(self, state: PlanningLocalState) -> list[EvidenceDraftV1]:
        retrieval_result = state.get("retrieval_result")
        if retrieval_result is None:
            return []
        return resolve_evidence_projection(
            store=self._evidence_store,
            run_id=state["run_id"],
            retrieval_result=retrieval_result,
        )

    def _run_plan_attempt(
        self,
        state: PlanningLocalState,
        *,
        mode: str,
        confirmation_response: ConfirmationResponseV1 | None,
    ) -> tuple[AnswerDraftV1 | ActionPlanDraftV1, list[StructuredLLMResult]]:
        analysis_result = state.get("analysis_result")
        retrieval_result = state.get("retrieval_result")
        if analysis_result is not None and retrieval_result is not None:
            return super()._run_plan_attempt(
                state,
                mode=mode,
                confirmation_response=confirmation_response,
            )
        if not isinstance(self._agent, CanonicalOptionalInputPlanningAgent):
            raise TypeError("optional Planning requires canonical optional-input agent")

        request = request_from_state(state)
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        evidence_drafts = self._evidence_drafts(state)
        review_state = state["plan_review"]
        review_issues: list[ReviewIssueV1] = []
        review_summary: str | None = None
        if review_state is not None:
            review_issues = [cast(ReviewIssueV1, dict(issue)) for issue in review_state["issues"]]
            review_summary = review_state.get("summary")

        if mode == "answer_only":
            ensure_llm_call_budget(state)
            llm_result = self._agent.invoke_answer_with_optional_analysis(
                request_intent=request_intent,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                request=request,
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_answer_with_optional_analysis(
                llm_result,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
            )
            return result, [llm_result]

        if mode == "revise_answer":
            raise ValueError(
                "ANSWER_ONLY bypasses Review; optional-input revise_answer is unreachable"
            )

        frozen_routes = _require_state_value(
            _frozen_output_routes(state), "frozen_output_routes"
        )
        ensure_llm_call_budget(state, provider_calls_requested=len(frozen_routes))
        if mode == "draft_plan":
            route_results = self._argument_orchestrator.compose(
                request=request,
                request_intent=request_intent,
                output_routes=frozen_routes,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
            )
            previous_plan = None
        else:
            route_results = self._argument_orchestrator.revise(
                request=request,
                request_intent=request_intent,
                output_routes=frozen_routes,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                plan_draft=_require_state_value(state["plan_draft"], "plan_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
            )
            previous_plan = _require_state_value(state["plan_draft"], "plan_draft")

        result = assemble_plan_with_optional_analysis(
            request_intent=request_intent,
            analysis_result=analysis_result,
            evidence_drafts=evidence_drafts,
            output_routes=tuple(route_result.route for route_result in route_results),
            argument_candidates=tuple(route_result.candidate for route_result in route_results),
            plan_id_factory=self._id_factory,
            action_id_factory=self._id_factory,
            previous_plan=previous_plan,
        )
        return result, _real_llm_results(route_results)

    def _finalize_resolved(
        self,
        state: PlanningLocalState,
        *,
        result: AnswerDraftV1 | ActionPlanDraftV1,
    ) -> PlanningLocalState:
        analysis_result = state.get("analysis_result")
        retrieval_result = state.get("retrieval_result")
        if analysis_result is not None and retrieval_result is not None:
            return super()._finalize_resolved(state, result=result)

        evidence_drafts = self._evidence_drafts(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        if "answer" in result:
            answer_result = validate_answer_with_optional_analysis(
                result,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
            )
            state_update = self._agent.build_answer_state_update(answer_result)
        else:
            plan_result = validate_plan_with_optional_analysis(
                result,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            state_update = self._agent.build_plan_state_update(plan_result)

        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(Any, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="planning",
                    agent_role="planning",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="planning",
                    node_name="finalize",
                    revision_increment=1 if mode == "revise_plan" else 0,
                ),
                "__planning_retry_confirmation__": False,
            },
            cast(GraphStateUpdateV1, state_update),
            cast(SupervisorDecisionV1, decision),
        )
        merged.pop(PLANNING_AGENT_LOCAL_KEY, None)
        merged.pop(PLANNING_MODE_KEY, None)
        merged.pop("__planning_result__", None)
        return cast(PlanningLocalState, merged)


__all__ = [
    "CanonicalOptionalPlanningSubgraph",
    "CanonicalOptionalWorkAnalysisSubgraph",
]
