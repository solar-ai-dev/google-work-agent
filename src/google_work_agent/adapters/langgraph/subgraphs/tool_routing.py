"""Deterministic Tool Route subgraph over the connector tool catalog.

Tool Route's only NEEDS_CONFIRMATION trigger is ``semantic_candidate_provider()``
(``determine_semantic_candidate``) raising -- the very first step of
``ToolRouteCoordinator.route()``. Every downstream deterministic step
(Registry binding, policy precondition merge, freeze, validate) only runs
after a candidate is already in hand, so there is never any "already
completed" downstream work to preserve across a confirmation pause: resolving
the ambiguity and re-running the rest of ``.route()`` is safe and cheap
(pure, side-effect-free) to redo exactly once per actual resume.

``route`` -> NEEDS_CONFIRMATION resolves with a real, nested-checkpoint
``interrupt()`` called from *inside* this compiled subgraph (in ``finalize``,
via the injected ``confirm_inline`` callback), mirroring
``RequestUnderstandingSubgraph`` (see that module's docstring for the full
node-replay-safety rationale). ``route`` never re-runs on resume: it already
completed and committed before the pause. If the resolved candidate is
itself still ambiguous, ``finalize`` does not call ``interrupt()`` a second
time inside the same already-resumed task; it cleanly returns with the next
round's interrupt payload already materialized, and a conditional self-loop
edge re-enters "finalize" as a genuinely new, separate task.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.confirmation_projection import (
    confirmation_response_from_state,
)
from google_work_agent.adapters.langgraph.graph_state import (
    TOOL_ROUTE_RESULT_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.route_translation import (
    RESUME_CONTRACT_VERSION,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    ToolRoutingInputState,
    ToolRoutingLocalState,
)
from google_work_agent.application.workflows import (
    BudgetDecision,
    ClarificationQuestionV1,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PolicyConfirmationReceiptV1,
    RunBudgetV1,
    ScopeExpansionRequiredV1,
    SupervisorDecisionV1,
    ToolRouteAgent,
    ToolRouteCoordinator,
    ToolRouteDisposition,
    ToolRouteResultV1,
    WorkflowPhase,
    check_llm_call_budget,
    consume_llm_provider_calls,
    route_supervisor,
)
from google_work_agent.application.workflows.request_understanding import (
    build_user_interrupt_v1,
)
from google_work_agent.application.workflows.scope_expansion import (
    build_policy_confirmation_receipt,
)
from google_work_agent.application.workflows.tool_routing import coarse_resource_category
from google_work_agent.domain import ConnectorToolCatalog
from google_work_agent.ports import LLMErrorCode, LLMInvocationError

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ToolRoutingLocalState],
    tuple[ConfirmationResponseV1 | None, dict[str, object] | None],
]
RecordPolicyConfirmationReceipt = Callable[[str, PolicyConfirmationReceiptV1], None]


class ToolRoutingSubgraph:
    """Resolve, bind, freeze, and publish one canonical Tool Route plan."""

    def __init__(
        self,
        *,
        coordinator: ToolRouteCoordinator,
        semantic_agent: ToolRouteAgent,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
        record_policy_confirmation_receipt: RecordPolicyConfirmationReceipt,
        id_factory: Callable[[], str],
    ) -> None:
        self._coordinator = coordinator
        self._semantic_agent = semantic_agent
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline
        self._record_policy_confirmation_receipt = record_policy_confirmation_receipt
        self._id_factory = id_factory

    def build(self) -> Any:
        graph = StateGraph(
            ToolRoutingLocalState,
            input_schema=ToolRoutingInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("route", self._route_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "route")
        graph.add_edge("route", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="tool_routing_subgraph")

    @staticmethod
    def _route_after_finalize(state: ToolRoutingLocalState) -> str:
        if state.get("__tool_route_retry_confirmation__"):
            return "finalize"
        return "end"

    def _run_one_route_attempt(
        self,
        state: ToolRoutingLocalState,
        *,
        confirmation_response: ConfirmationResponseV1 | None,
        current_interrupt_id: str | None = None,
    ) -> tuple[ToolRouteResultV1, RunBudgetV1]:
        """One full ``ToolRouteCoordinator.route()`` attempt: exactly one real
        semantic-candidate Provider call (plus a ``select_tool`` call only
        when the Registry has more than one eligible tool for some route),
        then the deterministic Registry/policy/freeze steps. Safe to call
        again for a later confirmation round -- see module docstring.
        """
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        request = request_from_state(state)
        retry_budget = cast(RunBudgetV1, state["retry_budget"])

        def _ensure_budget() -> None:
            decision = check_llm_call_budget(retry_budget)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise LLMInvocationError(
                    LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                    f"run LLM call budget exhausted: {decision['budget_reason_code']}",
                    retryable=False,
                )

        def _semantic_candidate_provider() -> Any:
            nonlocal retry_budget
            _ensure_budget()
            candidate, revised_retry_budget = self._semantic_agent.determine_semantic_candidate(
                request_intent=request_intent,
                request=request,
                retry_budget=retry_budget,
                confirmation_response=confirmation_response,
            )
            retry_budget = consume_llm_provider_calls(
                revised_retry_budget, provider_calls_consumed=1
            )
            return candidate

        def _select_tool(**kwargs: Any) -> Any:
            nonlocal retry_budget
            _ensure_budget()
            selected, revised_retry_budget = self._semantic_agent.select_tool_if_needed(
                request=request, retry_budget=retry_budget, **kwargs
            )
            retry_budget = consume_llm_provider_calls(
                revised_retry_budget, provider_calls_consumed=1
            )
            return selected

        policy_confirmation_receipts = cast(
            list[PolicyConfirmationReceiptV1], state.get("policy_confirmation_receipts", [])
        )
        result = self._coordinator.route(
            request_intent=request_intent,
            previous_plan=state.get("tool_route_plan"),
            semantic_candidate_provider=_semantic_candidate_provider,
            select_tool=_select_tool,
            policy_confirmation_receipts=policy_confirmation_receipts,
            current_interrupt_id=current_interrupt_id,
        )
        return result, retry_budget

    def _route_node(self, state: ToolRoutingLocalState) -> ToolRoutingLocalState:
        confirmation_response = confirmation_response_from_state(
            state,
            owner_subgraph="TOOL_ROUTE",
        )
        result, retry_budget = self._run_one_route_attempt(
            state, confirmation_response=confirmation_response
        )
        update: dict[str, object] = {
            **state,
            TOOL_ROUTE_RESULT_KEY: result,
            "retry_budget": retry_budget,
        }
        if result["disposition"] == "NEEDS_CONFIRMATION":
            # Materialized here -- not in finalize -- because this node
            # never replays on resume (it completes and commits before any
            # pause), so interrupt_id is generated exactly once and stays
            # stable across finalize's node-replay.
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                result=result, goal=request_intent["goal"]
            )
            update["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            update["user_interrupt"] = user_interrupt
            update["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return cast(ToolRoutingLocalState, update)

    def _materialize_confirmation_interrupt(
        self, *, result: ToolRouteResultV1, goal: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers -- via
        ``build_user_interrupt_v1``'s caller-supplied ``interrupt_id`` below
        -- only from an invocation that has not itself called ``interrupt()``
        yet: true for ``route`` (round 1, never replays) and for a *freshly
        self-looped* ``finalize`` invocation about to materialize round N+1
        and return (not yet resumed, so not yet replayed either).
        """
        signal = result.get("workflow_signal")
        question: ClarificationQuestionV1
        if isinstance(signal, Mapping) and signal.get("kind") == "SCOPE_EXPANSION_REQUIRED":
            question = self._scope_expansion_question(
                signal=cast(ScopeExpansionRequiredV1, signal), goal=goal
            )
        else:
            question = self._ambiguity_question(result=result, goal=goal)
        interrupt_id = self._id_factory()
        user_interrupt = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        confirmation_interrupt = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "owner_subgraph": "TOOL_ROUTE",
            "origin_target": question["origin_target"],
            "resume_target": {
                "subgraph_id": "TOOL_ROUTE",
                "node_id": "finalize",
                "graph_version": RESUME_CONTRACT_VERSION,
            },
            "resume_status": confirmation_resume_status("TOOL_ROUTE").value,
        }
        return user_interrupt, confirmation_interrupt

    @staticmethod
    def _ambiguity_question(*, result: ToolRouteResultV1, goal: str) -> ClarificationQuestionV1:
        return {
            "schema_version": 1,
            "origin_target": "tool_route.finalize",
            "question": "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요.",
            "affected_field_paths": [
                "requested_resource_hints",
                "requested_effect_hints",
            ],
            "reason_code": result["reason_codes"][0]
            if result["reason_codes"]
            else "TOOL_ROUTE_NEEDS_CONFIRMATION",
            "known_context_summary": goal,
            "options": [],
        }

    @staticmethod
    def _scope_expansion_question(
        *, signal: ScopeExpansionRequiredV1, goal: str
    ) -> ClarificationQuestionV1:
        """Closed-choice APPROVED/DECLINED confirmation for a Policy
        Precondition READ that falls outside the user's own explicit SCOPE
        constraints (FN-102A). Reuses the existing generic
        ``_validate_confirmation_option_scope`` -- no changes needed there."""
        resource_types = ", ".join(signal["required_resource_types"])
        return {
            "schema_version": 1,
            "origin_target": "tool_route.finalize",
            "question": (
                f"요청하신 작업을 처리하려면 {resource_types} 데이터를 추가로 "
                "확인해야 합니다. 진행할까요?"
            ),
            "affected_field_paths": ["requested_resource_hints"],
            "reason_code": signal["reason_codes"][0]
            if signal["reason_codes"]
            else "SCOPE_EXPANSION_REQUIRED",
            "known_context_summary": goal,
            "options": [
                {"option_id": "APPROVED", "label": "네, 확인하고 진행합니다"},
                {"option_id": "DECLINED", "label": "아니요, 진행하지 않습니다"},
            ],
        }

    def _finalize_node(self, state: ToolRoutingLocalState) -> ToolRoutingLocalState:
        result = cast(ToolRouteResultV1, state[TOOL_ROUTE_RESULT_KEY])

        if result["disposition"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    ToolRoutingLocalState,
                    {**state, "__tool_route_retry_confirmation__": False},
                )
            if result["disposition"] == "NEEDS_CONFIRMATION":
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring. Materialize the next round's payload
                # (self._id_factory() is safe here: this "finalize"
                # invocation has not itself paused yet) and cleanly return so
                # the self-loop conditional edge re-enters "finalize" as a
                # fresh, separate task for that round.
                request_intent = _require_state_value(
                    state["request_intent"], "request_intent"
                )
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    result=result, goal=request_intent["goal"]
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    ToolRoutingLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": user_interrupt,
                        "prompt_context": prompt_context,
                        "__tool_route_retry_confirmation__": True,
                    },
                )

        decision = route_supervisor(
            phase=WorkflowPhase.TOOL_ROUTING,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        merged = cast(
            dict[str, object],
            self._merge_decision(
                {**state, "__tool_route_retry_confirmation__": False},
                {"workflow_phase": WorkflowPhase.TOOL_ROUTING.value},
                decision,
            ),
        )
        merged.pop(TOOL_ROUTE_RESULT_KEY, None)
        return cast(ToolRoutingLocalState, merged)

    def _resolve_confirmation_inline(
        self, state: ToolRoutingLocalState
    ) -> tuple[ToolRoutingLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseV1`` with exactly one more
        ``_run_one_route_attempt`` call -- not by re-entering the ``route``
        node. Returns ``(state, None)`` when the caller must return ``state``
        immediately (not-applied/conflict end state); otherwise
        ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing ``interrupt()``)
        -- every value it depends on before the interrupt call is either read
        unchanged from state (set once by ``route``, a node that itself
        never replays) or is itself the idempotency-guarded, side-effect-free
        core in ``confirm_inline``.
        """
        pending_result = cast(ToolRouteResultV1, state[TOOL_ROUTE_RESULT_KEY])
        pending_signal = pending_result.get("workflow_signal")
        raw_interrupt = cast(Mapping[str, object], state["user_interrupt"])
        interrupt_id = cast(str, raw_interrupt["interrupt_id"])

        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                ToolRoutingLocalState, {**state, **early_return_patch}
            ), None
        assert confirmation_response is not None

        if isinstance(pending_signal, Mapping) and pending_signal.get("kind") == (
            "SCOPE_EXPANSION_REQUIRED"
        ):
            return self._resolve_scope_expansion(
                state,
                confirmation_response=confirmation_response,
                signal=cast(ScopeExpansionRequiredV1, pending_signal),
                interrupt_id=interrupt_id,
            )

        resolved_result, retry_budget = self._run_one_route_attempt(
            state, confirmation_response=confirmation_response
        )

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            ToolRoutingLocalState,
            {
                **state,
                TOOL_ROUTE_RESULT_KEY: resolved_result,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "retry_budget": retry_budget,
            },
        )
        return updated_state, resolved_result

    def _resolve_scope_expansion(
        self,
        state: ToolRoutingLocalState,
        *,
        confirmation_response: ConfirmationResponseV1,
        signal: ScopeExpansionRequiredV1,
        interrupt_id: str,
    ) -> tuple[ToolRoutingLocalState, Any]:
        """APPROVED -> the Application/Confirmation Controller (this method)
        builds one ``PolicyConfirmationReceiptV1``, appends it to Main State,
        and re-runs the exact same route attempt so the now-verified receipt
        unlocks the merge (``ToolRouteCoordinator._evaluate_scope_expansion``
        recognizes it and lets ``_merge_policy_preconditions`` proceed).
        DECLINED -> the mandatory Policy Precondition READ cannot be skipped
        (01-a-functional-definition.md:572, 12-test-design.md:169), so Tool
        Route is BLOCKED outright -- never re-attempted with a reduced plan.
        Neither branch materializes/executes the expanded READ itself; only
        the APPROVED re-attempt's ordinary Registry-bound InputToolRouteV1
        merge does that, downstream, exactly like any other input route.
        """
        decision: Literal["APPROVED", "DECLINED"] = (
            "APPROVED"
            if confirmation_response["selected_option_ids"] == ["APPROVED"]
            else "DECLINED"
        )
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        required_resource_types = tuple(signal["required_resource_types"])
        reason_codes = tuple(signal["reason_codes"])
        receipt = build_policy_confirmation_receipt(
            id_factory=self._id_factory,
            interrupt_id=interrupt_id,
            decision=decision,
            request_intent=request_intent,
            required_resource_types=required_resource_types,
            reason_codes=reason_codes,
            affected_route_ids=_scope_expansion_affected_route_ids(required_resource_types),
        )
        self._record_policy_confirmation_receipt(
            cast(str, state["run_id"]), receipt
        )
        receipts = [
            *cast(
                list[PolicyConfirmationReceiptV1],
                state.get("policy_confirmation_receipts", []),
            ),
            receipt,
        ]
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        if decision == "DECLINED":
            blocked_result: ToolRouteResultV1 = {
                "schema_version": 1,
                "disposition": ToolRouteDisposition.BLOCKED.value,
                "tool_route_plan": None,
                "workflow_signal": None,
                "reason_codes": ["SCOPE_EXPANSION_DECLINED"],
            }
            updated_state = cast(
                ToolRoutingLocalState,
                {
                    **state,
                    TOOL_ROUTE_RESULT_KEY: blocked_result,
                    "user_interrupt": None,
                    "prompt_context": prompt_context,
                    "policy_confirmation_receipts": receipts,
                },
            )
            return updated_state, blocked_result

        resolved_result, retry_budget = self._run_one_route_attempt(
            {**state, "policy_confirmation_receipts": receipts},
            confirmation_response=None,
            current_interrupt_id=interrupt_id,
        )
        updated_state = cast(
            ToolRoutingLocalState,
            {
                **state,
                TOOL_ROUTE_RESULT_KEY: resolved_result,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "retry_budget": retry_budget,
                "policy_confirmation_receipts": receipts,
            },
        )
        return updated_state, resolved_result


_SCOPE_EXPANSION_TRIGGER_ROUTES = {
    "TASK": "TASK:CREATE",
    "CALENDAR": "CALENDAR_EVENT:CREATE",
}
"""The Receipt's ``affected_route_ids`` identify the output write action
that pulled in the out-of-scope read, not a specific ``route_id`` (those are
freshly regenerated by ``ToolRouteCoordinator._bind_output_routes`` on every
attempt, including the post-approval re-attempt, so they are never stable
across a confirmation round -- see ``_run_one_route_attempt``'s docstring).
This mapping is exactly the two triggers ``PolicyPreconditionResolver``
implements (``TASK + CREATE``, ``CALENDAR_EVENT + CREATE``); it does not
generalize beyond them."""


def _scope_expansion_affected_route_ids(required_resource_types: tuple[str, ...]) -> list[str]:
    categories = {
        coarse_resource_category(resource_type) for resource_type in required_resource_types
    }
    return sorted(
        _SCOPE_EXPANSION_TRIGGER_ROUTES[category]
        for category in categories
        if category in _SCOPE_EXPANSION_TRIGGER_ROUTES
    )


def build_tool_routing_subgraph(
    *,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    merge_decision: MergeDecision,
    semantic_agent: ToolRouteAgent,
    confirm_inline: ConfirmInline,
    record_policy_confirmation_receipt: RecordPolicyConfirmationReceipt,
) -> Any:
    """Build the Tool Route node at the LangGraph composition boundary."""

    return ToolRoutingSubgraph(
        coordinator=ToolRouteCoordinator(tool_catalog=tool_catalog, id_factory=id_factory),
        semantic_agent=semantic_agent,
        merge_decision=merge_decision,
        confirm_inline=confirm_inline,
        record_policy_confirmation_receipt=record_policy_confirmation_receipt,
        id_factory=id_factory,
    ).build()


__all__ = ["ToolRoutingSubgraph", "build_tool_routing_subgraph"]
