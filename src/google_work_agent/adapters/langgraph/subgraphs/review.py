"""Review native LangGraph subgraph.

init -> review -> result_validate -> finalize
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.graph_state import (
    REVIEW_AGENT_LOCAL_KEY,
    REVIEW_MODE_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanReviewAgent,
    ReviewResult,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
)

MergeDecision = Callable[[GraphState, GraphStateUpdateV1, SupervisorDecisionV1], GraphState]


class ReviewSubgraph:
    """Builds and executes the ``review`` native subgraph."""

    def __init__(
        self,
        *,
        agent: PlanReviewAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._init_node)
        graph.add_node("review", self._review_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "review")
        graph.add_edge("review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="review_subgraph")

    def _init_node(self, state: GraphState) -> GraphState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        mode = (
            "recheck"
            if review is not None and review.get("status") == ReviewResult.REVISE.value
            else "inspect"
        )
        prompt_ref = (
            self._agent.recheck_prompt_ref if mode == "recheck" else self._agent.inspect_prompt_ref
        )
        local_state = build_agent_local_state(
            agent_role="review",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "mode": mode,
                "has_answer_draft": state.get("answer_draft") is not None,
                "has_plan_draft": state.get("plan_draft") is not None,
            },
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: local_state,
            REVIEW_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=invocation_id,
                subgraph_namespace="review",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
                revision_increment=1 if mode == "recheck" else 0,
            ),
        }

    def _review_node(self, state: GraphState) -> GraphState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        if mode == "recheck":
            llm_result = self._agent.invoke_recheck_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                allowed_statuses=frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value}),
            )
            llm_call_id = f"{request.run_id}:review.recheck"
        else:
            llm_result = self._agent.invoke_inspect_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
            llm_call_id = f"{request.run_id}:review.inspect"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="review",
                node_name="review",
                llm_call_id=llm_call_id,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="review",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
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
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="review",
                    agent_role="review",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="review",
                    node_name="finalize",
                ),
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(REVIEW_AGENT_LOCAL_KEY, None)
        merged.pop(REVIEW_MODE_KEY, None)
        return merged
