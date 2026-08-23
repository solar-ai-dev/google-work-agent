"""Work-analysis native LangGraph subgraph.

init -> analyze -> result_validate -> finalize

``analyze`` -> ``NEEDS_CONFIRMATION`` resolves with a real, nested-checkpoint
``interrupt()`` called from *inside* this compiled subgraph (in ``finalize``,
via the injected ``confirm_inline`` callback), not from the shared Main-Graph
``waiting_confirmation`` node. ``analyze``/``result_validate`` never re-run on
resume: they already completed and committed before the pause, so
``finalize``'s node-replay on resume only re-derives its own (pure) decision
from that committed output, then makes exactly one more direct
``invoke_analyze_llm_from_retrieval_result`` call carrying the validated
``ConfirmationResponseV1`` -- not a second traversal of ``analyze``.

If that resolution is *itself* still ambiguous, ``finalize`` does NOT call
``interrupt()`` a second time within the same (already-resumed) task -- any
Domain write or Provider call between two interrupt() calls in one task would
replay on every future resume of that task, since only interrupt() itself is
replay-cached. Instead ``finalize`` cleanly returns with the next round's
interrupt payload already materialized, and a conditional self-loop edge
re-enters "finalize" as a genuinely new, separate task -- the same pattern
Request Understanding/Tool Route/Retrieval already use for their own
Confirmation rounds.
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
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.main.state import (
    ANALYSIS_AGENT_LOCAL_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    WorkAnalysisInputState,
    WorkAnalysisLocalState,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.request_understanding import (
    build_user_interrupt_v1,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.orchestration.work_analysis import (
    WorkAnalysisAgent,
    build_work_analysis_clarification_question,
)
from google_work_agent.ports import StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [WorkAnalysisLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]


class WorkAnalysisSubgraph:
    """Builds and executes the ``work_analysis`` native subgraph."""

    def __init__(
        self,
        *,
        agent: WorkAnalysisAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            WorkAnalysisLocalState,
            input_schema=WorkAnalysisInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("analyze", self._analyze_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "analyze")
        graph.add_edge("analyze", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="work_analysis_subgraph")

    @staticmethod
    def _route_after_finalize(state: WorkAnalysisLocalState) -> str:
        if state.get("__work_analysis_retry_confirmation__"):
            return "finalize"
        return "end"

    def _init_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="work_analysis",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "retrieval_result": _require_state_value(
                    state["retrieval_result"], "retrieval_result"
                ),
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
        """One ``work_analysis.analyze`` LLM call. Safe to call again for a
        later confirmation round -- ``retrieval_result`` and its
        ``RunScopedEvidenceStore``-resolved evidence projection are already
        frozen (materialized by Retrieval before this subgraph ever started),
        never re-derived, re-fetched, or re-written here.
        """
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = resolve_evidence_projection(
            store=self._evidence_store,
            run_id=state["run_id"],
            retrieval_result=retrieval_result,
        )
        receipt_refs: list[str] = []
        for receipt in state.get("policy_confirmation_receipts", []):
            if not isinstance(receipt, Mapping):
                continue
            receipt_id = receipt.get("confirmation_receipt_id")
            if isinstance(receipt_id, str) and receipt_id:
                receipt_refs.append(receipt_id)
        ensure_llm_call_budget(state)
        llm_result = self._agent.invoke_analyze_llm_from_retrieval_result(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            retrieval_result=retrieval_result,
            evidence_drafts=evidence_drafts,
            request=request_from_state(state),
            policy_confirmation_receipt_refs=receipt_refs,
            confirmation_response=confirmation_response,
        )
        result = self._agent.build_output_from_llm_result_from_retrieval_result(
            llm_result,
            retrieval_result=retrieval_result,
            evidence_drafts=evidence_drafts,
        )
        return result, llm_result

    def _analyze_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        result, llm_result = self._run_analyze_attempt(state, confirmation_response=None)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "ANALYZE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        next_state: WorkAnalysisLocalState = {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "analysis_result": result,
            "retry_budget": consume_llm_call_budget(
                state, provider_calls_consumed=llm_result.structured_output_attempts
            ),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="analysis",
                node_name="analyze",
                llm_call_id=f"{request.run_id}:analysis.analyze",
                prompt_ref=self._agent.analyze_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }
        if result["status"] == "NEEDS_CONFIRMATION":
            # Materialized here -- not in finalize -- because this node never
            # replays on resume (it completes and commits before any pause),
            # so interrupt_id is generated exactly once and stays stable
            # across finalize's node-replay.
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                result=result, request_intent=request_intent
            )
            next_state["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            next_state["user_interrupt"] = cast(Any, user_interrupt)
            next_state["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return next_state

    def _materialize_confirmation_interrupt(
        self, *, result: WorkAnalysisResultV1, request_intent: RequestIntentV2
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers only from
        an invocation that has not itself called ``interrupt()`` yet: true
        for ``analyze`` (round 1, never replays) and for a *freshly
        self-looped* ``finalize`` invocation about to materialize round N+1
        and return (not yet resumed, so not yet replayed either).
        ``origin_target`` stays ``analysis.analyze`` -- the already-allowlisted
        (``CONFIRMATION_ORIGIN_TARGETS``) value this question always had, even
        though ``interrupt()`` itself now lives in ``finalize``; Tool
        Route/Retrieval's own origin_target/interrupt-owning-node split shows
        this is already an accepted convention, not a new one.
        """
        question = build_work_analysis_clarification_question(
            result=result, request_intent=request_intent
        )
        interrupt_id = self._id_factory()
        user_interrupt = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        confirmation_interrupt = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "owner_subgraph": "WORK_ANALYSIS",
            "origin_target": question["origin_target"],
            "resume_target": {
                "subgraph_id": "WORK_ANALYSIS",
                "node_id": "finalize",
                "graph_version": RESUME_CONTRACT_VERSION,
            },
            "resume_status": confirmation_resume_status("WORK_ANALYSIS").value,
        }
        return user_interrupt, confirmation_interrupt

    def _result_validate_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        result = _require_state_value(state["analysis_result"], "analysis_result")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "analysis_result": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="analysis",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        result = _require_state_value(state["analysis_result"], "analysis_result")

        if result["status"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    WorkAnalysisLocalState,
                    {**state, "__work_analysis_retry_confirmation__": False},
                )
            if result["status"] == "NEEDS_CONFIRMATION":
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring / Request Understanding/Retrieval's
                # established rationale. Materialize the next round's
                # payload (self._id_factory() is safe here: this "finalize"
                # invocation has not itself paused yet) and cleanly return so
                # the self-loop conditional edge re-enters "finalize" as a
                # fresh, separate task for that round.
                request_intent = _require_state_value(
                    state["request_intent"], "request_intent"
                )
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    result=result, request_intent=request_intent
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    WorkAnalysisLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": cast(Any, user_interrupt),
                        "prompt_context": prompt_context,
                        "__work_analysis_retry_confirmation__": True,
                    },
                )

        return self._finalize_resolved(state, result=result)

    def _resolve_confirmation_inline(
        self, state: WorkAnalysisLocalState
    ) -> tuple[WorkAnalysisLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseV1`` with exactly one more
        ``work_analysis.analyze`` call -- not by re-entering ``analyze`` or
        re-deriving ``retrieval_result``/evidence. Returns ``(state, None)``
        when the caller must return ``state`` immediately (not-applied/conflict
        end state); otherwise ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing ``interrupt()``)
        -- every value it depends on before the interrupt call is either read
        unchanged from state (set once by ``analyze``, a node that itself
        never replays) or is itself the idempotency-guarded, side-effect-free
        core in ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                WorkAnalysisLocalState, {**state, **early_return_patch}
            ), None
        assert confirmation_response is not None

        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        resolved_result, llm_result = self._run_analyze_attempt(
            state, confirmation_response=confirmation_response
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "ANALYZE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], resolved_result)

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            WorkAnalysisLocalState,
            {
                **state,
                ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "analysis_result": resolved_result,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "retry_budget": consume_llm_call_budget(
                    state, provider_calls_consumed=llm_result.structured_output_attempts
                ),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="work_analysis",
                    agent_role="work_analysis",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="analysis",
                    node_name="finalize",
                    llm_call_id=f"{request.run_id}:analysis.analyze.confirm",
                    prompt_ref=self._agent.analyze_prompt_ref,
                    llm_call_increment=llm_result.structured_output_attempts,
                ),
            },
        )
        return updated_state, resolved_result

    def _finalize_resolved(
        self, state: WorkAnalysisLocalState, *, result: WorkAnalysisResultV1
    ) -> WorkAnalysisLocalState:
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
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
                ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="work_analysis",
                    agent_role="work_analysis",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="analysis",
                    node_name="finalize",
                ),
                "__work_analysis_retry_confirmation__": False,
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return cast(WorkAnalysisLocalState, merged)
