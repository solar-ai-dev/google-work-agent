"""Planning native LangGraph subgraph.

init -> plan -> result_validate -> finalize
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.graph_state import (
    PLANNING_AGENT_LOCAL_KEY,
    PLANNING_MODE_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    PlanningInputState,
    PlanningLocalState,
)
from google_work_agent.application.workflows import (
    ActionPlanDraftV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RequestIntentV2,
    ReviewResult,
    SolutionPlanningAgent,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.workflows.handoff_contracts import ReviewIssueV1
from google_work_agent.application.workflows.planning_argument_orchestrator import (
    PlanningArgumentOrchestrator,
    RouteArgumentResult,
)
from google_work_agent.application.workflows.planning_plan_assembler import (
    assemble_action_plan_draft_v1_compat,
)
from google_work_agent.application.workflows.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.workflows.tool_routing import (
    OutputToolRouteV1,
    ToolRoutePlanV2,
    output_routes,
)
from google_work_agent.ports import PromptReference, StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]


_WRITE_EFFECT_HINTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})


def planning_mode_from_request_intent(
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None = None,
) -> str:
    """Deterministic answer_only/draft_plan selection (GAP-F1)."""
    if tool_route_plan is not None:
        return (
            "draft_plan"
            if tool_route_plan["output_plan"]["output_mode"] == "ACTION"
            else "answer_only"
        )
    has_write_effect = any(
        effect in _WRITE_EFFECT_HINTS
        for effect in request_intent.get("requested_effect_hints", [])
    )
    return "draft_plan" if has_write_effect else "answer_only"


class PlanningSubgraph:
    """Builds and executes the ``planning`` native subgraph."""

    def __init__(
        self,
        *,
        agent: SolutionPlanningAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        argument_orchestrator: PlanningArgumentOrchestrator | None = None,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        # The base runtime can construct this subgraph before the canonical
        # composition layer injects the per-route orchestrator.  The public
        # canonical runtime replaces the Planning binding and recompiles the
        # graph before any invocation is exposed to callers.
        self._argument_orchestrator = argument_orchestrator

    def build(self) -> Any:
        graph = StateGraph(
            PlanningLocalState,
            input_schema=PlanningInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("plan", self._plan_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "plan")
        graph.add_edge("plan", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="planning_subgraph")

    def _init_node(self, state: PlanningLocalState) -> PlanningLocalState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        analysis_result = _require_state_value(state["analysis_result"], "analysis_result")
        tool_route_plan = state.get("tool_route_plan")
        mode = planning_mode_from_request_intent(request_intent, tool_route_plan)
        if review is not None and review.get("status") == ReviewResult.REVISE.value:
            mode = "revise_answer" if state.get("answer_draft") is not None else "revise_plan"
        prompt_ref = self._prompt_ref_for_mode(mode)
        local_state = build_agent_local_state(
            agent_role="planning",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": request_intent,
                "analysis_result": analysis_result,
                "mode": mode,
                "output_routes": list(output_routes(tool_route_plan)) if tool_route_plan else [],
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

    def _plan_node(self, state: PlanningLocalState) -> PlanningLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        review_state = state["plan_review"]
        review_issues: list[ReviewIssueV1] = []
        review_summary: str | None = None
        if review_state is not None:
            review_issues = [cast(ReviewIssueV1, dict(issue)) for issue in review_state["issues"]]
            review_summary = review_state.get("summary")
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = resolve_evidence_projection(
            store=self._evidence_store,
            run_id=state["run_id"],
            retrieval_result=retrieval_result,
        )
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        analysis_result = _require_state_value(state["analysis_result"], "analysis_result")
        result: AnswerDraftV1 | ActionPlanDraftV1
        llm_results: list[StructuredLLMResult] = []
        canonical_action_path = False

        if mode == "answer_only":
            ensure_llm_call_budget(state)
            llm_result = self._agent.invoke_answer_only_llm_from_evidence(
                request_intent=request_intent,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                request=request,
            )
            llm_results.append(llm_result)
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=analysis_result,
            )
            llm_call_id = f"{request.run_id}:planning.answer_only"
        elif mode == "draft_plan" and self._uses_canonical_action_path():
            canonical_action_path = True
            frozen_routes = _required_frozen_output_routes(state)
            ensure_llm_call_budget(state, provider_calls_requested=len(frozen_routes))
            route_results = self._required_argument_orchestrator().compose(
                request=request,
                request_intent=request_intent,
                output_routes=frozen_routes,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
            )
            llm_results.extend(_actual_llm_results(route_results))
            result = assemble_action_plan_draft_v1_compat(
                request_intent=request_intent,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
                output_routes=frozen_routes,
                argument_candidates=tuple(item.candidate for item in route_results),
                plan_id_factory=self._id_factory,
                action_id_factory=self._id_factory,
                revision=1,
            )
            llm_call_id = f"{request.run_id}:planning.compose_arguments"
        elif mode == "draft_plan":
            ensure_llm_call_budget(state)
            llm_result = self._agent.invoke_draft_plan_llm_from_evidence(
                request_intent=request_intent,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                request=request,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_results.append(llm_result)
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=analysis_result,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_call_id = f"{request.run_id}:planning.draft_plan"
        elif mode == "revise_answer":
            ensure_llm_call_budget(state)
            llm_result = self._agent.invoke_revise_answer_llm_from_evidence(
                request_intent=request_intent,
                answer_draft=_require_state_value(state["answer_draft"], "answer_draft"),
                review_issues=[dict(issue) for issue in review_issues],
                review_summary=review_summary,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                request=request,
            )
            llm_results.append(llm_result)
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=analysis_result,
            )
            llm_call_id = f"{request.run_id}:planning.revise_answer"
        elif self._uses_canonical_action_path():
            canonical_action_path = True
            frozen_routes = _required_frozen_output_routes(state)
            previous_plan = _require_state_value(state["plan_draft"], "plan_draft")
            revision_call_count = _revision_call_count(
                previous_plan=previous_plan,
                review_issues=review_issues,
            )
            if revision_call_count:
                ensure_llm_call_budget(
                    state,
                    provider_calls_requested=revision_call_count,
                )
            route_results = self._required_argument_orchestrator().revise(
                request=request,
                request_intent=request_intent,
                output_routes=frozen_routes,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                plan_draft=previous_plan,
                review_issues=review_issues,
                review_summary=review_summary,
            )
            llm_results.extend(_actual_llm_results(route_results))
            planning_revisions_used = int(state["retry_budget"]["planning_revisions_used"])
            result = assemble_action_plan_draft_v1_compat(
                request_intent=request_intent,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
                output_routes=frozen_routes,
                argument_candidates=tuple(item.candidate for item in route_results),
                plan_id_factory=self._id_factory,
                action_id_factory=self._id_factory,
                revision=max(1, planning_revisions_used + 1),
                previous_plan=previous_plan,
            )
            llm_call_id = f"{request.run_id}:planning.compose_arguments.revise"
        else:
            ensure_llm_call_budget(state)
            llm_result = self._agent.invoke_revise_plan_llm_from_evidence(
                request_intent=request_intent,
                plan_draft=_require_state_value(state["plan_draft"], "plan_draft"),
                review_issues=[dict(issue) for issue in review_issues],
                review_summary=review_summary,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                request=request,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_results.append(llm_result)
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=analysis_result,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_call_id = f"{request.run_id}:planning.revise_plan"

        provider_calls_consumed = sum(item.provider_calls_consumed for item in llm_results)
        repair_count = sum(max(0, item.structured_output_attempts - 1) for item in llm_results)
        if canonical_action_path:
            updated_local = dict(local_state)
            updated_local["candidate_output"] = cast(dict[str, object], result)
            updated_local["schema_repair_count"] = repair_count
        else:
            if len(llm_results) != 1:
                raise ValueError("non-canonical Planning path must execute exactly one LLM call")
            updated_local = dict(record_llm_result(local_state, llm_results[0]))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "__planning_result__": result,
            "retry_budget": consume_llm_call_budget(
                state,
                provider_calls_consumed=provider_calls_consumed,
            ),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="planning",
                node_name="plan",
                llm_call_id=llm_call_id,
                llm_call_increment=provider_calls_consumed,
                repair_increment=repair_count,
            ),
        }

    def _result_validate_node(self, state: PlanningLocalState) -> PlanningLocalState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        result = state["__planning_result__"]
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = result
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="planning",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: PlanningLocalState) -> PlanningLocalState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        result = state["__planning_result__"]
        if "answer" in result:
            answer_result = validate_answer_draft_v1(
                result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            state_update = self._agent.build_answer_state_update(answer_result)
        else:
            plan_result = validate_action_plan_draft_v1(
                result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            state_update = self._agent.build_plan_state_update(plan_result)
        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(MultiAgentGraphState, state),
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
            },
            state_update,
            decision,
        )
        merged.pop(PLANNING_AGENT_LOCAL_KEY, None)
        merged.pop(PLANNING_MODE_KEY, None)
        merged.pop("__planning_result__", None)
        return cast(PlanningLocalState, merged)

    def _uses_canonical_action_path(self) -> bool:
        return (
            self._graph_profile is GraphProfile.SIX_ROLE_BASELINE
            and self._argument_orchestrator is not None
        )

    def _required_argument_orchestrator(self) -> PlanningArgumentOrchestrator:
        if self._argument_orchestrator is None:
            raise ValueError("PlanningArgumentOrchestrator is not configured")
        return self._argument_orchestrator

    def _prompt_ref_for_mode(self, mode: str) -> PromptReference:
        if self._uses_canonical_action_path() and mode == "draft_plan":
            return self._required_argument_orchestrator().prompt_ref
        if self._uses_canonical_action_path() and mode == "revise_plan":
            return self._required_argument_orchestrator().revise_prompt_ref
        return {
            "answer_only": self._agent.answer_only_prompt_ref,
            "draft_plan": self._agent.draft_plan_prompt_ref,
            "revise_answer": self._agent.revise_answer_prompt_ref,
            "revise_plan": self._agent.revise_plan_prompt_ref,
        }[mode]


def _actual_llm_results(
    route_results: tuple[RouteArgumentResult, ...],
) -> list[StructuredLLMResult]:
    return [item.llm_result for item in route_results if item.llm_result is not None]


def _revision_call_count(
    *,
    previous_plan: ActionPlanDraftV1,
    review_issues: list[ReviewIssueV1],
) -> int:
    count = 0
    for action in previous_plan["actions"]:
        if action["effect"] == "READ":
            continue
        if any(
            not issue.get("affected_action_ids", [])
            or action["action_id"] in issue.get("affected_action_ids", [])
            for issue in review_issues
        ):
            count += 1
    return count


def _required_frozen_output_routes(
    state: PlanningLocalState,
) -> tuple[OutputToolRouteV1, ...]:
    routes = _frozen_output_routes(state)
    if not routes:
        raise ValueError("ACTION Planning requires frozen output routes")
    return routes


def _frozen_output_routes(
    state: PlanningLocalState,
) -> tuple[OutputToolRouteV1, ...] | None:
    plan = state.get("tool_route_plan")
    return None if plan is None else output_routes(plan)


def _frozen_read_tool_ids(state: PlanningLocalState) -> frozenset[str]:
    plan = state.get("tool_route_plan")
    if plan is None:
        return frozenset()
    return frozenset(
        tool_id
        for route in plan["input_plan"]["input_routes"]
        for tool_id in route["allowed_read_tool_ids"]
    )
