"""Planning native LangGraph subgraph.

init -> plan -> result_validate -> finalize

``plan`` -> ``NEEDS_CONFIRMATION`` (possible from all four modes -- see
``ANSWER_DRAFT_OUTPUT_SCHEMA``/``ACTION_PLAN_DRAFT_OUTPUT_SCHEMA``, both of
which allow it) resolves with a real, nested-checkpoint ``interrupt()``
called from *inside* this compiled subgraph (in ``finalize``, via the
injected ``confirm_inline`` callback), not from the shared Main-Graph
``waiting_confirmation`` node. ``plan``/``result_validate`` never re-run on
resume: they already completed and committed before the pause, so
``finalize``'s node-replay on resume only re-derives its own (pure) decision
from that committed output, then makes exactly one more direct Planning
semantic call (whichever of the four ``invoke_*_llm_from_evidence`` methods
matches the already-frozen ``mode``) carrying the validated
``ConfirmationResponseV1`` -- not a second traversal of ``plan``.

If that resolution is *itself* still ambiguous, ``finalize`` does NOT call
``interrupt()`` a second time within the same (already-resumed) task -- see
Request Understanding/Tool Route/Retrieval/Work Analysis's own established
rationale. Instead ``finalize`` cleanly returns with the next round's
interrupt payload already materialized, and a conditional self-loop edge
re-enters "finalize" as a genuinely new, separate task.
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
from google_work_agent.application.workflows import (
    ActionPlanDraftV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RequestIntentV2,
    ReviewResult,
    SolutionPlanningAgent,
    SupervisorDecisionV1,
    WorkflowPhase,
    build_solution_planning_clarification_question,
    route_supervisor,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.workflows.request_understanding import (
    build_user_interrupt_v1,
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
from google_work_agent.ports import StructuredLLMResult

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [PlanningLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]


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
        return graph.compile(name="planning_subgraph")

    @staticmethod
    def _route_after_finalize(state: PlanningLocalState) -> str:
        if state.get("__planning_retry_confirmation__"):
            return "finalize"
        return "end"

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

    def _run_plan_attempt(
        self,
        state: PlanningLocalState,
        *,
        mode: str,
        confirmation_response: ConfirmationResponseV1 | None,
    ) -> tuple[AnswerDraftV1 | ActionPlanDraftV1, StructuredLLMResult]:
        """One Planning semantic LLM call for the already-frozen ``mode``.

        Safe to call again for a later confirmation round -- ``mode``,
        ``retrieval_result``'s resolved evidence projection,
        ``tool_route_plan``'s frozen output routes/read tool ids, and any
        ``answer_draft``/``plan_draft``/``plan_review`` inputs are already
        frozen in state, never re-derived or re-fetched.
        """
        request = request_from_state(state)
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
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
        elif mode == "draft_plan":
            llm_result = self._agent.invoke_draft_plan_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
        elif mode == "revise_answer":
            llm_result = self._agent.invoke_revise_answer_llm_from_evidence(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                answer_draft=_require_state_value(state["answer_draft"], "answer_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
                evidence_drafts=evidence_drafts,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
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
                confirmation_response=confirmation_response,
            )
            result = self._agent.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                frozen_output_routes=_frozen_output_routes(state),
                frozen_read_tool_ids=_frozen_read_tool_ids(state),
            )
        return result, llm_result

    def _plan_node(self, state: PlanningLocalState) -> PlanningLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        result, llm_result = self._run_plan_attempt(state, mode=mode, confirmation_response=None)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        next_state: PlanningLocalState = {
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
                llm_call_id=f"{request.run_id}:planning.{mode}",
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
        self, *, result: AnswerDraftV1 | ActionPlanDraftV1, request_intent: RequestIntentV2
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers only from
        an invocation that has not itself called ``interrupt()`` yet: true
        for ``plan`` (round 1, never replays) and for a *freshly self-looped*
        ``finalize`` invocation about to materialize round N+1 and return
        (not yet resumed, so not yet replayed either). ``origin_target`` is
        ``planning.answer_only`` for answer_only/revise_answer or
        ``planning.draft_plan`` for draft_plan/revise_plan (already
        allowlisted in ``CONFIRMATION_ORIGIN_TARGETS``) -- Retrieval/Work
        Analysis's own origin_target/interrupt-owning-node split shows this
        is already an accepted convention, not a new one.
        """
        question = build_solution_planning_clarification_question(
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
            "owner_subgraph": "PLANNING",
            "origin_target": question["origin_target"],
            "resume_target": {
                "subgraph_id": "PLANNING",
                "node_id": "finalize",
                "graph_version": RESUME_CONTRACT_VERSION,
            },
            "resume_status": confirmation_resume_status("PLANNING").value,
        }
        return user_interrupt, confirmation_interrupt

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
        result = state["__planning_result__"]

        if result["status"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    PlanningLocalState,
                    {**state, "__planning_retry_confirmation__": False},
                )
            if result["status"] == "NEEDS_CONFIRMATION":
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
        self, state: PlanningLocalState
    ) -> tuple[PlanningLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseV1`` with exactly one more Planning
        semantic call for the already-frozen ``mode`` -- not by re-entering
        ``plan`` or re-deriving ``retrieval_result``/evidence/frozen output
        routes. Returns ``(state, None)`` when the caller must return
        ``state`` immediately (not-applied/conflict end state); otherwise
        ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing ``interrupt()``)
        -- every value it depends on before the interrupt call is either read
        unchanged from state (set once by ``plan``, a node that itself never
        replays) or is itself the idempotency-guarded, side-effect-free core
        in ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                PlanningLocalState, {**state, **early_return_patch}
            ), None
        assert confirmation_response is not None

        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        mode = state[PLANNING_MODE_KEY]
        resolved_result, llm_result = self._run_plan_attempt(
            state, mode=mode, confirmation_response=confirmation_response
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], resolved_result)

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            PlanningLocalState,
            {
                **state,
                PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "__planning_result__": resolved_result,
                "user_interrupt": None,
                "prompt_context": prompt_context,
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
                    node_name="finalize",
                    llm_call_id=f"{request.run_id}:planning.{mode}.confirm",
                    llm_call_increment=llm_result.structured_output_attempts,
                ),
            },
        )
        return updated_state, resolved_result

    def _finalize_resolved(
        self, state: PlanningLocalState, *, result: AnswerDraftV1 | ActionPlanDraftV1
    ) -> PlanningLocalState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
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
                "__planning_retry_confirmation__": False,
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
