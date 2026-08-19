"""Request-understanding native LangGraph subgraph (init -> classify -> finalize).

``classify`` -> ``NEEDS_CONFIRMATION`` resolves with a real, nested-checkpoint
``interrupt()`` called from *inside* this compiled subgraph (in ``finalize``,
via the injected ``confirm_inline`` callback), not from the shared Main-Graph
``waiting_confirmation`` node. ``classify`` never re-runs on resume: it already
completed and committed before the pause, so ``finalize``'s node-replay on
resume only re-derives its own (pure) decision from that committed output,
then makes exactly one more direct ``invoke_classify_llm`` call carrying the
validated ``ConfirmationResponseV1`` -- not a second traversal of the
``classify`` node.

If that resolution is *itself* still ambiguous, ``finalize`` does NOT call
``interrupt()`` a second time within the same (already-resumed) task -- any
Domain write or Provider call between two interrupt() calls in one task would
replay on every future resume of that task, since only interrupt() itself is
replay-cached. Instead ``finalize`` cleanly returns with the next round's
interrupt payload already materialized, and a conditional self-loop edge
re-enters "finalize" as a genuinely new, separate task -- the same "repeat a
node as its own fresh checkpoint" pattern Retrieval's own bounded local loop
already uses elsewhere in this codebase. Each round is therefore its own real
nested-subgraph interrupt/resume, not a shared Main-Graph restart.
"""

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
from google_work_agent.adapters.langgraph.confirmation_projection import (
    confirmation_response_from_state,
)
from google_work_agent.adapters.langgraph.graph_state import (
    REQUEST_AGENT_LOCAL_KEY,
    REQUEST_OUTPUT_KEY,
    ParentGraphState,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.route_translation import (
    RESUME_CONTRACT_VERSION,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    RequestUnderstandingInputState,
    RequestUnderstandingLocalState,
)
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RequestUnderstandingAgent,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
)
from google_work_agent.application.workflows.request_understanding import (
    build_user_interrupt_v1,
    materialize_request_intent_artifact,
    validate_clarification_question_v1,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [RequestUnderstandingLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]


class RequestUnderstandingSubgraph:
    """Builds and executes the ``request_understanding`` native subgraph."""

    def __init__(
        self,
        *,
        agent: RequestUnderstandingAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            RequestUnderstandingLocalState,
            input_schema=RequestUnderstandingInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("classify", self._classify_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "classify")
        graph.add_edge("classify", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="request_understanding_subgraph")

    @staticmethod
    def _route_after_finalize(state: RequestUnderstandingLocalState) -> str:
        if state.get("__request_understanding_retry_confirmation__"):
            return "finalize"
        return "end"

    def _init_node(self, state: RequestUnderstandingLocalState) -> RequestUnderstandingLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="request_understanding",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_text": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            prompt_ref=self._agent.prompt_ref,
        )
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=invocation_id,
                subgraph_namespace="request_understanding",
                node_name="init",
                prompt_ref=self._agent.prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _classify_node(
        self, state: RequestUnderstandingLocalState
    ) -> RequestUnderstandingLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        confirmation_response = confirmation_response_from_state(
            state,
            owner_subgraph="REQUEST_UNDERSTANDING",
        )
        ensure_llm_call_budget(state)
        llm_result = self._agent.invoke_classify_llm(
            request, confirmation_response=confirmation_response
        )
        output = self._agent.build_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "CLASSIFY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        update: dict[str, object] = {
            **state,
            REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            REQUEST_OUTPUT_KEY: output,
            "retry_budget": consume_llm_call_budget(
                state, provider_calls_consumed=llm_result.structured_output_attempts
            ),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="request_understanding",
                node_name="classify",
                llm_call_id=f"{request.run_id}:request_understanding.classify",
                prompt_ref=self._agent.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }
        if output["result"] == "NEEDS_CONFIRMATION" and output.get("clarification") is not None:
            # Materialized here -- not in finalize -- because this node never
            # replays on resume (it completes and commits before any pause),
            # so interrupt_id is generated exactly once and stays stable
            # across finalize's node-replay.
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                clarification=output["clarification"]
            )
            update["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            update["user_interrupt"] = user_interrupt
            update["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return cast(RequestUnderstandingLocalState, update)

    def _materialize_confirmation_interrupt(
        self, *, clarification: object
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()`` only from an invocation that
        has not itself called ``interrupt()`` yet -- true for ``classify``
        (round 1, never replays) and for a *freshly self-looped* ``finalize``
        invocation about to materialize round N+1 and return (not yet
        resumed, so not yet replayed either).
        """
        question = validate_clarification_question_v1(clarification)
        interrupt_id = self._id_factory()
        user_interrupt = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        confirmation_interrupt = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "owner_subgraph": "REQUEST_UNDERSTANDING",
            "origin_target": question["origin_target"],
            "resume_target": {
                "subgraph_id": "REQUEST_UNDERSTANDING",
                "node_id": "finalize",
                "graph_version": RESUME_CONTRACT_VERSION,
            },
            "resume_status": confirmation_resume_status("REQUEST_UNDERSTANDING").value,
        }
        return user_interrupt, confirmation_interrupt

    def _finalize_node(
        self, state: RequestUnderstandingLocalState
    ) -> RequestUnderstandingLocalState:
        request = request_from_state(state)
        output = state[REQUEST_OUTPUT_KEY]

        if output["result"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, output = self._resolve_confirmation_inline(state, request=request)
            if output is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    RequestUnderstandingLocalState,
                    {**state, "__request_understanding_retry_confirmation__": False},
                )
            if output["result"] == "NEEDS_CONFIRMATION" and output.get("clarification") is not None:
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring. Materialize the next round's payload
                # (self._id_factory() is safe here: this "finalize"
                # invocation has not itself paused yet) and cleanly return so
                # the self-loop conditional edge re-enters "finalize" as a
                # fresh, separate task for that round.
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    clarification=output["clarification"]
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    RequestUnderstandingLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": user_interrupt,
                        "prompt_context": prompt_context,
                        "__request_understanding_retry_confirmation__": True,
                    },
                )

        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        if output["request_intent"] is not None and "meta" not in output["request_intent"]:
            output = {
                **output,
                "request_intent": materialize_request_intent_artifact(
                    output["request_intent"],
                    artifact_id=self._id_factory(),
                ),
            }
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, output["result"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="request_understanding",
                    agent_role="request_understanding",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="request_understanding",
                    node_name="finalize",
                ),
                REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "__request_understanding_retry_confirmation__": False,
            },
            self._agent.build_state_update(output, request=request),
            decision,
        )
        merged.pop(REQUEST_AGENT_LOCAL_KEY, None)
        merged.pop(REQUEST_OUTPUT_KEY, None)
        return cast(RequestUnderstandingLocalState, merged)

    def _resolve_confirmation_inline(
        self,
        state: RequestUnderstandingLocalState,
        *,
        request: Any,
    ) -> tuple[RequestUnderstandingLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseV1`` with exactly one more direct
        ``invoke_classify_llm`` call -- not by re-entering the ``classify``
        node. Returns ``(state, None)`` when the caller must return ``state``
        immediately (not-applied/conflict end state); otherwise
        ``(updated_state, resolved_output)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing ``interrupt()``)
        -- every value it depends on before the interrupt call is either read
        unchanged from state (set once by ``classify``, a node that itself
        never replays) or is itself the idempotency-guarded, side-effect-free
        core in ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                RequestUnderstandingLocalState, {**state, **early_return_patch}
            ), None
        assert confirmation_response is not None

        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        ensure_llm_call_budget(state)
        llm_result = self._agent.invoke_classify_llm(
            request, confirmation_response=confirmation_response
        )
        resolved_output = self._agent.build_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "CLASSIFY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], resolved_output)

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            RequestUnderstandingLocalState,
            {
                **state,
                REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                REQUEST_OUTPUT_KEY: resolved_output,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "retry_budget": consume_llm_call_budget(
                    state, provider_calls_consumed=llm_result.structured_output_attempts
                ),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="request_understanding",
                    agent_role="request_understanding",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="request_understanding",
                    node_name="finalize",
                    llm_call_id=f"{request.run_id}:request_understanding.classify.confirm",
                    prompt_ref=self._agent.prompt_ref,
                    llm_call_increment=llm_result.structured_output_attempts,
                ),
            },
        )
        return updated_state, resolved_output
