"""Runtime-active Planning graph for the approved 0.9.1 Prompt bundle.

The atomic 0.9.2 graph remains in ``planning.graph`` and fails closed unless
its semantic invoker is explicitly supplied. Product runtime must keep using
the approved per-route prompt flow until the 0.9.2 activation gates pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
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
from google_work_agent.adapters.langgraph.route_translation import (
    RESUME_CONTRACT_VERSION,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    PlanningInputState,
    PlanningLocalState,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.request_understanding import (
    build_user_interrupt_v1,
)
from google_work_agent.ports import StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, object], Any]
ConfirmInline = Callable[
    [PlanningLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]
PlanningResult = AnswerDraftV1 | ActionPlanDraftV1


class RuntimeActivePlanningSubgraph:
    """Execute the currently approved Planning prompts and graph lifecycle."""

    def __init__(
        self,
        *,
        agent: object,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
        evidence_store: object,
        confirm_inline: ConfirmInline,
        argument_orchestrator: object,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline
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
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="runtime_active_planning_subgraph")

    @staticmethod
    def _route_after_finalize(state: PlanningLocalState) -> str:
        return "finalize" if state.get("__planning_retry_confirmation__") else "end"

    def _init_node(self, state: PlanningLocalState) -> PlanningLocalState:
        raise NotImplementedError

    def _run_plan_attempt(
        self,
        state: PlanningLocalState,
        *,
        mode: str,
        confirmation_response: ConfirmationResponseV1 | None,
    ) -> tuple[PlanningResult, list[StructuredLLMResult]]:
        raise NotImplementedError

    def _finalize_resolved(
        self,
        state: PlanningLocalState,
        *,
        result: PlanningResult,
    ) -> PlanningLocalState:
        raise NotImplementedError

    def _plan_node(self, state: PlanningLocalState) -> PlanningLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        result, llm_results = self._run_plan_attempt(
            state,
            mode=mode,
            confirmation_response=None,
        )
        recorded_local = local_state
        for llm_result in llm_results:
            recorded_local = record_llm_result(recorded_local, llm_result)
        updated_local = cast(dict[str, object], dict(recorded_local))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        total_attempts = sum(item.structured_output_attempts for item in llm_results)
        next_state = cast(
            PlanningLocalState,
            {
                **state,
                PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "__planning_result__": result,
                "retry_budget": consume_llm_call_budget(
                    state,
                    provider_calls_consumed=total_attempts,
                ),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="planning",
                    agent_role="planning",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="planning",
                    node_name="plan",
                    llm_call_id=f"{request.run_id}:planning.{mode}",
                    llm_call_increment=total_attempts,
                    repair_increment=max(0, total_attempts - len(llm_results)),
                ),
            },
        )
        if result["status"] == "NEEDS_CONFIRMATION":
            request_intent = _require_state_value(
                state["request_intent"],
                "request_intent",
            )
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
        result: PlanningResult,
        request_intent: RequestIntentV2,
    ) -> tuple[dict[str, object], dict[str, object]]:
        from google_work_agent.application.orchestration.solution_planning import (
            build_solution_planning_clarification_question,
        )

        question = build_solution_planning_clarification_question(
            result=result,
            request_intent=request_intent,
        )
        interrupt_id = self._id_factory()
        return (
            {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id},
            {
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "owner_subgraph": "PLANNING",
                "origin_target": question["origin_target"],
                "resume_target": {
                    "subgraph_id": "PLANNING",
                    "node_id": "finalize",
                    "graph_version": RESUME_CONTRACT_VERSION,
                },
                "resume_status": confirmation_resume_status("PLANNING").value,
            },
        )

    def _result_validate_node(self, state: PlanningLocalState) -> PlanningLocalState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        result = state["__planning_result__"]
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = result
        return cast(
            PlanningLocalState,
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
                    node_name="result_validate",
                ),
            },
        )

    def _finalize_node(self, state: PlanningLocalState) -> PlanningLocalState:
        result = cast(PlanningResult, state["__planning_result__"])
        if result["status"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"),
            Mapping,
        ):
            state, resolved = self._resolve_confirmation_inline(state)
            if resolved is None:
                return cast(
                    PlanningLocalState,
                    {**state, "__planning_retry_confirmation__": False},
                )
            result = resolved
            if result["status"] == "NEEDS_CONFIRMATION":
                request_intent = _require_state_value(
                    state["request_intent"],
                    "request_intent",
                )
                user_interrupt, confirmation_interrupt = (
                    self._materialize_confirmation_interrupt(
                        result=result,
                        request_intent=request_intent,
                    )
                )
                prompt_context = dict(
                    cast(dict[str, object], state.get("prompt_context", {}))
                )
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    PlanningLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": cast(Any, user_interrupt),
                        "prompt_context": prompt_context,
                        "__planning_retry_confirmation__": True,
                    },
                )
        return self._finalize_resolved(state, result=result)

    def _resolve_confirmation_inline(
        self,
        state: PlanningLocalState,
    ) -> tuple[PlanningLocalState, PlanningResult | None]:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(PlanningLocalState, {**state, **early_return_patch}), None
        if confirmation_response is None:
            raise RuntimeError("planning confirmation response is unavailable")

        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        mode = state[PLANNING_MODE_KEY]
        result, llm_results = self._run_plan_attempt(
            state,
            mode=mode,
            confirmation_response=confirmation_response,
        )
        recorded_local = local_state
        for llm_result in llm_results:
            recorded_local = record_llm_result(recorded_local, llm_result)
        updated_local = cast(dict[str, object], dict(recorded_local))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        total_attempts = sum(item.structured_output_attempts for item in llm_results)
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        return (
            cast(
                PlanningLocalState,
                {
                    **state,
                    PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                    "__planning_result__": result,
                    "user_interrupt": None,
                    "prompt_context": prompt_context,
                    "retry_budget": consume_llm_call_budget(
                        state,
                        provider_calls_consumed=total_attempts,
                    ),
                    "trace_context": merge_trace_context(
                        state,
                        graph_profile=self._graph_profile.value,
                        agent_subgraph_id="planning",
                        agent_role="planning",
                        agent_invocation_id=local_state["invocation_id"],
                        subgraph_namespace="planning",
                        node_name="finalize",
                        llm_call_id=f"{request.run_id}:planning.{mode}.confirm",
                        llm_call_increment=total_attempts,
                    ),
                },
            ),
            result,
        )


__all__ = ["RuntimeActivePlanningSubgraph"]
