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
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import PlanningLocalState
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
from google_work_agent.application.workflows.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.workflows.tool_routing import (
    OutputToolRouteV1,
    ToolRoutePlanV2,
    output_routes,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]


_WRITE_EFFECT_HINTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})


def planning_mode_from_request_intent(
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None = None,
) -> str:
    """Deterministic answer_only/draft_plan selection (GAP-F1).

    ``tool_route_plan.output_plan.output_mode`` is the official ANSWER/ACTION
    authority (Q2-X) -- Tool Route always runs before Planning in the SIX
    release path, so this is the branch actually taken there. The
    ``requested_effect_hints``-based fallback below only matters for
    SINGLE_BASELINE/THREE_STAGE's standalone Planning subgraph invocation,
    which does not have a ``tool_route_plan`` to consult; RequestIntentV2
    carries no explicit disposition field (unlike the retired V1
    ``response_disposition``), so ACTION is inferred the same way Tool
    Route's own deterministic compatibility path does: any effect hint that
    isn't a plain READ. Falls back to ``answer_only`` when no write effect
    is present, rather than guessing an action the user did not ask for
    (docs/01-b-policy-definition-v2.8.md POL-EVD-003 / "Answer-only에서
    불필요한 Action을 생성하지 않는다").
    """
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
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store

    def build(self) -> Any:
        graph = StateGraph(
            PlanningLocalState,
            input_schema=GraphState,
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
        prompt_ref = {
            "answer_only": self._agent.answer_only_prompt_ref,
            "draft_plan": self._agent.draft_plan_prompt_ref,
            "revise_answer": self._agent.revise_answer_prompt_ref,
            "revise_plan": self._agent.revise_plan_prompt_ref,
        }[mode]
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
        review_issues: list[dict[str, object]] = []
        review_summary: str | None = None
        if review_state is not None:
            review_issues = [dict(issue) for issue in review_state["issues"]]
            review_summary = review_state.get("summary")
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = resolve_evidence_projection(
            store=self._evidence_store,
            run_id=state["run_id"],
            retrieval_result=retrieval_result,
        )
        result: AnswerDraftV1 | ActionPlanDraftV1
        ensure_llm_call_budget(state)
        if mode == "answer_only":
            llm_result = self._agent.invoke_answer_only_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.answer_only"
        elif mode == "draft_plan":
            llm_result = self._agent.invoke_draft_plan_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_call_id = f"{request.run_id}:planning.draft_plan"
        elif mode == "revise_answer":
            llm_result = self._agent.invoke_revise_answer_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                answer_draft=_require_state_value(state["answer_draft"], "answer_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.revise_answer"
        else:
            llm_result = self._agent.invoke_revise_plan_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                plan_draft=_require_state_value(state["plan_draft"], "plan_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
            llm_call_id = f"{request.run_id}:planning.revise_plan"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "__planning_result__": result,
            "retry_budget": consume_llm_call_budget(
                state, provider_calls_consumed=llm_result.structured_output_attempts
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
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
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
