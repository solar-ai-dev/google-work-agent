"""Review native LangGraph subgraph.

init -> review -> result_validate -> finalize

``review`` -> ``CONFIRM`` (only reachable from ``mode="inspect"`` --
``review.recheck``'s tool set is restricted to ``review_pass``/``review_block``,
so ``mode="recheck"`` can never produce it) resolves with a real,
nested-checkpoint ``interrupt()`` called from *inside* this compiled
subgraph (in ``finalize``, via the injected ``confirm_inline`` callback),
not from the shared Main-Graph ``waiting_confirmation`` node.
``review``/``result_validate`` never re-run on resume: they already
completed and committed before the pause, so ``finalize``'s node-replay on
resume only re-derives its own (pure) decision from that committed output,
then makes exactly one more direct ``invoke_inspect_llm_from_evidence`` call
carrying the validated ``ConfirmationResponseV1`` -- not a second traversal
of ``review``.

If that resolution is *itself* still ambiguous, ``finalize`` does NOT call
``interrupt()`` a second time within the same (already-resumed) task -- see
Request Understanding/Tool Route/Retrieval/Work Analysis/Planning's own
established rationale. Instead ``finalize`` cleanly returns with the next
round's interrupt payload already materialized, and a conditional self-loop
edge re-enters "finalize" as a genuinely new, separate task.
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
from google_work_agent.adapters.langgraph.graph_state import (
    REVIEW_AGENT_LOCAL_KEY,
    REVIEW_MODE_KEY,
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
    ReviewInputState,
    ReviewLocalState,
)
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanReviewAgent,
    PlanReviewResultV1,
    RequestIntentV2,
    ReviewResult,
    SupervisorDecisionV1,
    WorkflowPhase,
    build_plan_review_clarification_question,
    route_supervisor,
)
from google_work_agent.application.workflows.request_understanding import (
    build_user_interrupt_v1,
)
from google_work_agent.application.workflows.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.ports import StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ReviewLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]


class ReviewSubgraph:
    """Builds and executes the ``review`` native subgraph."""

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
        return graph.compile(name="review_subgraph")

    @staticmethod
    def _route_after_finalize(state: ReviewLocalState) -> str:
        if state.get("__review_retry_confirmation__"):
            return "finalize"
        return "end"

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

    def _run_review_attempt(
        self,
        state: ReviewLocalState,
        *,
        mode: str,
        confirmation_response: ConfirmationResponseV1 | None,
    ) -> tuple[PlanReviewResultV1, StructuredLLMResult]:
        """One Review semantic LLM call for the already-frozen ``mode``.

        Safe to call again for a later confirmation round -- ``mode``,
        ``retrieval_result``'s resolved evidence projection, and
        ``answer_draft``/``plan_draft`` are already frozen in state, never
        re-derived or re-fetched. Only ``mode="inspect"`` can ever receive
        ``confirmation_response`` -- ``mode="recheck"`` is restricted to
        PASS/BLOCK and can neither produce nor resolve CONFIRM.
        """
        request = request_from_state(state)
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
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
        else:
            llm_result = self._agent.invoke_inspect_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
        return result, llm_result

    def _review_node(self, state: ReviewLocalState) -> ReviewLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        result, llm_result = self._run_review_attempt(state, mode=mode, confirmation_response=None)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        next_state: ReviewLocalState = {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "retry_budget": consume_llm_call_budget(
                state, provider_calls_consumed=llm_result.structured_output_attempts
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
        }
        if result["status"] == "CONFIRM":
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
        self, *, result: PlanReviewResultV1, request_intent: RequestIntentV2
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers only from
        an invocation that has not itself called ``interrupt()`` yet: true
        for ``review`` (round 1, never replays) and for a *freshly
        self-looped* ``finalize`` invocation about to materialize round N+1
        and return (not yet resumed, so not yet replayed either).
        ``origin_target`` is always ``review.inspect`` (already allowlisted
        in ``CONFIRMATION_ORIGIN_TARGETS``) -- the only Review prompt that
        can ever produce CONFIRM.
        """
        question = build_plan_review_clarification_question(
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
            "owner_subgraph": "REVIEW",
            "origin_target": question["origin_target"],
            "resume_target": {
                "subgraph_id": "REVIEW",
                "node_id": "finalize",
                "graph_version": RESUME_CONTRACT_VERSION,
            },
            "resume_status": confirmation_resume_status("REVIEW").value,
        }
        return user_interrupt, confirmation_interrupt

    def _result_validate_node(self, state: ReviewLocalState) -> ReviewLocalState:
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

    def _finalize_node(self, state: ReviewLocalState) -> ReviewLocalState:
        result = _require_state_value(state["plan_review"], "plan_review")

        if result["status"] == "CONFIRM" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    ReviewLocalState,
                    {**state, "__review_retry_confirmation__": False},
                )
            if result["status"] == "CONFIRM":
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring / the other owners' established
                # rationale. Materialize the next round's payload
                # (self._id_factory() is safe here: this "finalize"
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
        self, state: ReviewLocalState
    ) -> tuple[ReviewLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseV1`` with exactly one more
        ``review.inspect`` call -- not by re-entering ``review`` or
        re-deriving ``retrieval_result``/evidence. Returns ``(state, None)``
        when the caller must return ``state`` immediately (not-applied/conflict
        end state); otherwise ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing ``interrupt()``)
        -- every value it depends on before the interrupt call is either read
        unchanged from state (set once by ``review``, a node that itself
        never replays) or is itself the idempotency-guarded, side-effect-free
        core in ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                ReviewLocalState, {**state, **early_return_patch}
            ), None
        assert confirmation_response is not None

        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        mode = state[REVIEW_MODE_KEY]
        resolved_result, llm_result = self._run_review_attempt(
            state, mode=mode, confirmation_response=confirmation_response
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], resolved_result)

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            ReviewLocalState,
            {
                **state,
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "plan_review": resolved_result,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "retry_budget": consume_llm_call_budget(
                    state, provider_calls_consumed=llm_result.structured_output_attempts
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
        )
        return updated_state, resolved_result

    def _finalize_resolved(
        self, state: ReviewLocalState, *, result: PlanReviewResultV1
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
