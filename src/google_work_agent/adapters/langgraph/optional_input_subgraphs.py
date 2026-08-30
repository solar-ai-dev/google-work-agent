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

from typing import Any, cast

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.state import (
    PLANNING_AGENT_LOCAL_KEY,
    PLANNING_MODE_KEY,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    PlanningLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    _frozen_output_routes,
    _frozen_read_tool_ids,
    _real_llm_results,
    planning_answer_path_selected,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.runtime_active_graph import (
    RuntimeActivePlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import (
    WorkAnalysisSubgraph,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    ReviewIssueV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.optional_agent_inputs import (
    assemble_plan_with_optional_analysis,
    validate_plan_with_optional_analysis,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.ports.llm import StructuredLLMResult


class CanonicalOptionalWorkAnalysisSubgraph(WorkAnalysisSubgraph):
    """Work Analysis that accepts the Canonical no-Retrieval entry path."""

    pass


class CanonicalOptionalPlanningSubgraph(RuntimeActivePlanningSubgraph):
    """Temporary #118 ACTION-only delegate with optional upstream inputs."""

    def _init_node(self, state: PlanningLocalState) -> PlanningLocalState:
        if state.get("analysis_result") is None and isinstance(
            state.get("work_analysis_result"), dict
        ):
            compatibility = _temporary_action_analysis_projection(
                cast(dict[str, object], state["work_analysis_result"]),
                self._evidence_drafts(state),
            )
            prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
            prompt_context["temporary_action_analysis_projection"] = compatibility
            state = cast(
                PlanningLocalState,
                {
                    **state,
                    "analysis_result": compatibility,
                    "prompt_context": prompt_context,
                },
            )
        invocation_id = self._id_factory()
        review = state.get("plan_review")
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        if planning_answer_path_selected(cast(dict[str, object], state)):
            raise ValueError("ANSWER Planning must use the canonical two-node runtime")
        mode = "draft_plan"
        if review is not None and review.get("status") == "REVISE":
            mode = "revise_plan"
        prompt_ref = {
            "draft_plan": self._argument_orchestrator.prompt_ref,
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
        confirmation_response: ConfirmationResponseProjectionV1 | None,
    ) -> tuple[ActionPlanDraftV1, list[StructuredLLMResult]]:
        analysis_result = state.get("analysis_result")
        request = request_from_state(state)
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        evidence_drafts = self._evidence_drafts(state)
        review_state = state.get("plan_review")
        review_issues: list[ReviewIssueV1] = []
        review_summary: str | None = None
        if review_state is not None:
            review_issues = [cast(ReviewIssueV1, dict(issue)) for issue in review_state["issues"]]
            review_summary = review_state.get("summary")

        frozen_routes = _require_state_value(_frozen_output_routes(state), "frozen_output_routes")
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
        result: ActionPlanDraftV1,
    ) -> PlanningLocalState:
        analysis_result = state.get("analysis_result")
        evidence_drafts = self._evidence_drafts(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
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


def _temporary_action_analysis_projection(
    result: dict[str, object], evidence: list[EvidenceDraftV1]
) -> WorkAnalysisResultV1:
    """#118-only bridge; ANSWER never consumes this legacy V1 projection."""
    facts = cast(list[dict[str, object]], result.get("work_facts", []))
    evidence_refs = cast(list[str], result.get("evidence_refs", []))
    resources = [
        {"resource_handle": draft["resource_handle"]}
        for draft in evidence
        if draft.get("resource_handle")
    ]
    resource_handles = [cast(str, item["resource_handle"]) for item in resources]
    segments = [
        {
            "segment_id": draft["segment_id"],
            "resource_handle": draft["resource_handle"],
        }
        for draft in evidence
        if draft.get("segment_id") and draft.get("resource_handle")
    ]
    ambiguities = cast(list[dict[str, object]], result.get("ambiguities", []))
    return cast(
        WorkAnalysisResultV1,
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "summary": str(result.get("action_necessity_reason") or "Work analysis complete."),
            "findings": [
                {
                    "schema_version": 1,
                    "finding_id": fact.get("fact_id", f"fact-{index}"),
                    "kind": "RELATIONSHIP",
                    "statement": str(fact.get("value", fact.get("subject", "fact"))),
                    "evidence_refs": list(cast(list[str], fact.get("evidence_refs", []))),
                    "resource_refs": list(resource_handles),
                    "segment_refs": [],
                    "related_resource_handles": list(resource_handles),
                    "reason_codes": ["EVIDENCE_SUPPORTED"],
                }
                for index, fact in enumerate(facts, start=1)
            ],
            "missing_information": [
                str(item.get("description"))
                for item in ambiguities
                if item.get("requires_confirmation") and item.get("description")
            ],
            "confirmation": None,
            "blockers": [],
            "evidence_refs": list(evidence_refs),
            "resource_refs": resources,
            "segment_refs": segments,
        },
    )
