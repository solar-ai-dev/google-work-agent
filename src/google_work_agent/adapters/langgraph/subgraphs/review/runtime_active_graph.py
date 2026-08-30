"""Runtime-active Review graph for the approved 0.9.1 Prompt bundle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.main.state import (
    REVIEW_AGENT_LOCAL_KEY,
    REVIEW_MODE_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    ReviewInputState,
    ReviewLocalState,
)
from google_work_agent.application.orchestration.confirmation import (
    build_user_interrupt_v1,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    ReviewResult,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    PlanReviewResultV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.plan_review import (
    PlanReviewAgent,
    build_plan_review_clarification_question,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.ports.llm import StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ReviewLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class RuntimeActiveReviewSubgraph:
    """Execute the approved inspect/recheck prompts and Review lifecycle."""

    def __init__(
        self,
        *,
        agent: PlanReviewAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            ReviewLocalState,
            input_schema=ReviewInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("review", self._review_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "review")
        graph.add_edge("review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="runtime_active_review_subgraph")

    @staticmethod
    def _route_after_finalize(state: ReviewLocalState) -> str:
        return "finalize" if state.get("__review_retry_confirmation__") else "end"

    def _init_node(self, state: ReviewLocalState) -> ReviewLocalState:
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
        return cast(
            ReviewLocalState,
            {
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
            },
        )

    def _run_review_attempt(
        self,
        state: ReviewLocalState,
        *,
        mode: str,
        confirmation_response: ConfirmationResponseProjectionV1 | None,
    ) -> tuple[PlanReviewResultV1, StructuredLLMResult]:
        request = request_from_state(state)
        retrieval_result = _require_state_value(
            state["retrieval_result"],
            "retrieval_result",
        )
        evidence_drafts = resolve_evidence_projection(
            store=self._evidence_store,
            run_id=state["run_id"],
            retrieval_result=retrieval_result,
        )
        ensure_llm_call_budget(state)
        if mode == "recheck":
            llm_result = self._agent.invoke_recheck_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=self._action_analysis_result(state),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=self._action_analysis_result(state),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                allowed_statuses=frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value}),
            )
        else:
            llm_result = self._agent.invoke_inspect_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=self._action_analysis_result(state),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=self._action_analysis_result(state),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
        return result, llm_result

    @staticmethod
    def _action_analysis_result(state: ReviewLocalState) -> Any:
        value = state.get("analysis_result")
        if value is None:
            context = state.get("prompt_context")
            value = (
                context.get("temporary_action_analysis_projection")
                if isinstance(context, Mapping)
                else None
            )
        return _require_state_value(value, "analysis_result")

    def _review_node(self, state: ReviewLocalState) -> ReviewLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        result, llm_result = self._run_review_attempt(
            state,
            mode=mode,
            confirmation_response=None,
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        next_state = cast(
            ReviewLocalState,
            {
                **state,
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "plan_review": result,
                "retry_budget": consume_llm_call_budget(
                    state,
                    provider_calls_consumed=llm_result.structured_output_attempts,
                ),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="review",
                    agent_role="review",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="review",
                    node_name="review",
                    llm_call_id=f"{request.run_id}:review.{mode}",
                    llm_call_increment=llm_result.structured_output_attempts,
                    repair_increment=max(0, llm_result.structured_output_attempts - 1),
                ),
            },
        )
        if result["status"] == "CONFIRM":
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                result=result,
                request_intent=request_intent,
            )
            next_state["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            next_state["user_interrupt"] = cast(Any, user_interrupt)
            next_state["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return next_state

    def _materialize_confirmation_interrupt(
        self,
        *,
        result: PlanReviewResultV1,
        request_intent: RequestIntentV2,
    ) -> tuple[dict[str, object], dict[str, object]]:
        question = build_plan_review_clarification_question(
            result=result,
            request_intent=request_intent,
        )
        interrupt_id = self._id_factory()
        return (
            {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id},
            {
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "semantic_owner_id": "REVIEW",
                "origin_target": question["origin_target"],
            },
        )

    def _result_validate_node(self, state: ReviewLocalState) -> ReviewLocalState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return cast(
            ReviewLocalState,
            {
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
            },
        )

    def _finalize_node(self, state: ReviewLocalState) -> ReviewLocalState:
        result = _require_state_value(state["plan_review"], "plan_review")
        if result["status"] == "CONFIRM" and isinstance(state.get("user_interrupt"), Mapping):
            state, resolved = self._resolve_confirmation_inline(state)
            if resolved is None:
                return cast(ReviewLocalState, {**state, "__review_retry_confirmation__": False})
            result = resolved
            if result["status"] == "CONFIRM":
                request_intent = _require_state_value(state["request_intent"], "request_intent")
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    result=result,
                    request_intent=request_intent,
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    ReviewLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": cast(Any, user_interrupt),
                        "prompt_context": prompt_context,
                        "__review_retry_confirmation__": True,
                    },
                )
        return self._finalize_resolved(state, result=result)

    def _resolve_confirmation_inline(
        self,
        state: ReviewLocalState,
    ) -> tuple[ReviewLocalState, PlanReviewResultV1 | None]:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(ReviewLocalState, {**state, **early_return_patch}), None
        if confirmation_response is None:
            raise RuntimeError("review confirmation response is unavailable")
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        mode = state[REVIEW_MODE_KEY]
        result, llm_result = self._run_review_attempt(
            state,
            mode=mode,
            confirmation_response=confirmation_response,
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        return (
            cast(
                ReviewLocalState,
                {
                    **state,
                    REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                    "plan_review": result,
                    "user_interrupt": None,
                    "prompt_context": prompt_context,
                    "retry_budget": consume_llm_call_budget(
                        state,
                        provider_calls_consumed=llm_result.structured_output_attempts,
                    ),
                    "trace_context": merge_trace_context(
                        state,
                        graph_profile=self._graph_profile.value,
                        agent_subgraph_id="review",
                        agent_role="review",
                        agent_invocation_id=local_state["invocation_id"],
                        subgraph_namespace="review",
                        node_name="finalize",
                        llm_call_id=f"{request.run_id}:review.{mode}.confirm",
                        llm_call_increment=llm_result.structured_output_attempts,
                    ),
                },
            ),
            result,
        )

    def _finalize_resolved(
        self,
        state: ReviewLocalState,
        *,
        result: PlanReviewResultV1,
    ) -> ReviewLocalState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
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
                "__review_retry_confirmation__": False,
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(REVIEW_AGENT_LOCAL_KEY, None)
        merged.pop(REVIEW_MODE_KEY, None)
        return cast(ReviewLocalState, merged)


__all__ = ["RuntimeActiveReviewSubgraph"]
