"""Context-retriever native LangGraph subgraph.

init -> select_evidence -> selection_validate -> assess_sufficiency -> finalize
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.graph_state import (
    CONTEXT_AGENT_LOCAL_KEY,
    CONTEXT_CANONICAL_PLANS_KEY,
    CONTEXT_CURRENT_ROUND_NO_KEY,
    CONTEXT_DETAIL_CANDIDATES_KEY,
    CONTEXT_FOLLOWUP_OPERATION_KEY,
    CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY,
    CONTEXT_NEXT_PAGE_HANDLES_KEY,
    CONTEXT_QUERY_ATTEMPTS_KEY,
    CONTEXT_RAG_CANDIDATES_KEY,
    CONTEXT_READ_RESULT_HANDLES_KEY,
    CONTEXT_SEGMENT_HANDLES_KEY,
    CONTEXT_SELECTION_OUTPUT_KEY,
    CONTEXT_SUFFICIENCY_OUTPUT_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import ContextRetrievalLocalState
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    ContextRetrievalAgent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RetrievalRouteResultV1,
    SupervisorDecisionV1,
    WorkflowPhase,
    finalize_retrieval_result,
    initialize_current_round_no,
    retrieval_query_hash,
    route_supervisor,
    validate_context_retrieval_result_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    RetrievalNeedV1,
    RetrievalRequiredV1,
)
from google_work_agent.application.workflows.retrieval_attempts import (
    QueryAttempt,
    build_query_attempt,
    followup_planner_projection,
)
from google_work_agent.application.workflows.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.workflows.retrieval_planner_input import (
    followup_retrieval_planner_input,
    initial_retrieval_planner_input,
)
from google_work_agent.application.workflows.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.workflows.retrieval_read_cache import (
    ReadResultContinuationError,
    RunScopedReadResultCache,
)
from google_work_agent.application.workflows.retrieval_read_executor import RetrievalReadExecutor
from google_work_agent.application.workflows.retrieval_v2_contracts import RetrievalConstraintKindV1
from google_work_agent.application.workflows.source_fetch_plan_builder import (
    RouteConstraintPolicy,
    SourceFetchPlanBuilder,
)
from google_work_agent.application.workflows.source_fetch_plan_execution_projection import (
    project_for_legacy_read_executor,
)
from google_work_agent.application.workflows.tool_routing import (
    InputToolRouteV1,
    allowed_read_tool_ids,
    coarse_resource_category,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]


def _runtime_route_constraint_policies(
    routes: list[InputToolRouteV1],
) -> dict[str, RouteConstraintPolicy]:
    """Current read executor capability projection, kept outside planner authority.

    The legacy Google read port can deterministically execute keyword search
    only.  Other V2 semantic kinds remain valid contracts but require the
    later provider-translation migration; they are not silently discarded.
    """
    supported_by_resource = {
        "EMAIL": frozenset(
            {
                "TEMPORAL_RANGE",
                "PARTICIPANT",
                "KEYWORD",
                "RESOURCE_REF",
                "CONTAINER_REF",
                "STATUS_SCOPE",
            }
        ),
        "TASK": frozenset({"CONTAINER_REF"}),
        "CALENDAR": frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
    }
    return {
        route["route_id"]: RouteConstraintPolicy(
            supported_kinds=cast(
                frozenset[RetrievalConstraintKindV1],
                supported_by_resource[coarse_resource_category(route["resource_type"])],
            ),
            required_kinds=(
                frozenset({"KEYWORD"})
                if coarse_resource_category(route["resource_type"]) == "EMAIL"
                else frozenset()
            ),
        )
        for route in routes
        if coarse_resource_category(route["resource_type"]) in supported_by_resource
    }


def _planner_trace_context(state: ContextRetrievalLocalState) -> ObservabilityContext:
    request = request_from_state(state)
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=f"{request.run_id}:retrieval.plan_query",
    )


class ContextRetrieverSubgraph:
    """Builds and executes the ``context_retriever`` native subgraph."""

    def __init__(
        self,
        *,
        agent: ContextRetrievalAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: Callable[[str, str], None],
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        acquisition_agent: Any,
        retrieval_query_planner: RetrievalQueryPlannerAgent,
        source_fetch_plan_builder: SourceFetchPlanBuilder,
        read_result_cache: RunScopedReadResultCache,
        retrieval_read_executor: RetrievalReadExecutor,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._acquisition_agent = acquisition_agent
        self._retrieval_query_planner = retrieval_query_planner
        self._source_fetch_plan_builder = source_fetch_plan_builder
        self._read_result_cache = read_result_cache
        self._retrieval_read_executor = retrieval_read_executor
        # Pre-Prompt Runtime Closure: TASK routes' only supported semantic
        # constraint kind is CONTAINER_REF (_runtime_route_constraint_policies
        # below), but nothing ever populated validated_container_refs for the
        # planner call, so a TASK-resource plan_query could never validate.
        # Reuses the existing per-account Settings default_tasklist_id
        # concept (already the authoritative source resource_queries.py's
        # own _resolve_task_list_id falls back to) rather than adding a new
        # discovery Port/authority. When unset, TASK routes keep today's
        # existing (pre-existing, unrelated to this change) behavior.
        self._default_tasklist_id_provider = default_tasklist_id_provider

    def build(self) -> Any:
        graph = StateGraph(
            ContextRetrievalLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("plan_query", self._plan_initial_query_node)
        graph.add_node("execute_initial_read", self._execute_initial_read_node)
        graph.add_node("select_evidence", self._select_evidence_node)
        graph.add_node("selection_validate", self._selection_validate_node)
        graph.add_node("assess_sufficiency", self._assess_sufficiency_node)
        graph.add_node("plan_followup", self._plan_followup_node)
        graph.add_node("execute_next_page", self._execute_next_page_node)
        graph.add_node("execute_followup_search", self._execute_followup_search_node)
        graph.add_node("execute_detail", self._execute_detail_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_conditional_edges(
            "init",
            self._route_after_init,
            {"plan_query": "plan_query", "select_evidence": "select_evidence"},
        )
        graph.add_conditional_edges(
            "plan_query",
            self._route_after_plan_query,
            {
                "execute_initial_read": "execute_initial_read",
                "execute_followup_search": "execute_followup_search",
            },
        )
        graph.add_edge("execute_initial_read", "select_evidence")
        graph.add_edge("select_evidence", "selection_validate")
        graph.add_edge("selection_validate", "assess_sufficiency")
        graph.add_conditional_edges(
            "assess_sufficiency",
            self._route_after_sufficiency,
            {"plan_followup": "plan_followup", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "plan_followup",
            self._route_after_followup_plan,
            {
                "execute_next_page": "execute_next_page",
                "execute_followup_search": "execute_followup_search",
                "execute_detail": "execute_detail",
                "finalize": "finalize",
            },
        )
        graph.add_edge("execute_next_page", "select_evidence")
        graph.add_edge("execute_followup_search", "select_evidence")
        graph.add_edge("execute_detail", "select_evidence")
        graph.add_edge("finalize", END)
        return graph.compile(name="context_retriever_subgraph")

    def _init_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        invocation_id = self._id_factory()
        tool_route_plan = state.get("tool_route_plan")
        # Compatibility fixtures without a frozen route cannot continue a
        # chain; they are deterministically an initial round only.
        current_round_no = (
            0
            if tool_route_plan is None
            else initialize_current_round_no(
                prior_result=state.get("retrieval_result"),
                tool_route_plan=tool_route_plan,
            )
        )
        local_state = build_agent_local_state(
            agent_role="context_retriever",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "has_prior_acquisition": state.get("acquisition_result") is not None,
            },
            prompt_ref=self._agent.select_prompt_ref,
        )
        next_state: ContextRetrievalLocalState = {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: local_state,
            CONTEXT_CURRENT_ROUND_NO_KEY: current_round_no,
            CONTEXT_READ_RESULT_HANDLES_KEY: [],
            CONTEXT_SEGMENT_HANDLES_KEY: [],
            CONTEXT_QUERY_ATTEMPTS_KEY: [],
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=invocation_id,
                subgraph_namespace="context",
                node_name="init",
                prompt_ref=self._agent.select_prompt_ref,
                agent_invocation_increment=1,
            ),
        }
        # Q2-HANDOFF: WorkAnalysis/Review's RetrievalRequiredV1 re-entry --
        # the signal is consumed and cleared right here, and (only when a
        # prior read already exists to extend) turned into a genuine new
        # follow-up round via the same plan_followup machinery Retrieval's
        # own local loop uses. RetrievalRequiredV1 is never produced inside
        # this subgraph -- only Supervisor constructs it.
        retrieval_required = _retrieval_required_signal(state.get("workflow_signal"))
        if retrieval_required is not None:
            next_state["workflow_signal"] = None
            if state.get("acquisition_result") is not None:
                next_state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = followup_planner_projection(
                    current_round_no=current_round_no,
                    prior_query_attempts=[],
                    unresolved_sufficiency_issues=_needs_as_sufficiency_issues(
                        retrieval_required["needs"]
                    ),
                    read_result_summaries=self._bounded_read_result_summaries(next_state),
                )
        return next_state

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        acquisition_result = _require_state_value(state["acquisition_result"], "acquisition_result")
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._agent.build_segments_from_acquisition(acquisition_result)
        rag_candidates = self._agent.rag_retrieve(
            cast(list[Any], segments), request_intent=request_intent
        )
        selection = self._agent.select_evidence(
            request_intent=request_intent,
            request=request,
            rag_candidates=rag_candidates,
            segments=cast(list[Any], segments),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECT_EVIDENCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_RAG_CANDIDATES_KEY: rag_candidates,
            CONTEXT_SELECTION_OUTPUT_KEY: selection,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="select_evidence",
                llm_call_id=f"{request.run_id}:context.select_evidence",
                prompt_ref=self._agent.select_prompt_ref,
                llm_call_increment=1,
            ),
        }

    def _selection_validate_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        acquisition_result = _require_state_value(state["acquisition_result"], "acquisition_result")
        draft_bundle, evidence_drafts = self._agent.build_draft_context_bundle(
            selection_result=selection,
            acquisition_result=acquisition_result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECTION_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "context_bundle": draft_bundle,
            "evidence_drafts": evidence_drafts,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="selection_validate",
            ),
        }

    def _assess_sufficiency_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        sufficiency_result, llm_provider_result = self._agent.assess_sufficiency(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            request=request,
            tool_route_plan=state.get("tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            evidence_drafts=state["evidence_drafts"],
            retry_budget=state["retry_budget"],
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SUFFICIENCY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], sufficiency_result)
        next_state: ContextRetrievalLocalState = {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
            "llm_provider_result": llm_provider_result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="assess_sufficiency",
                llm_call_id=f"{request.run_id}:context.assess_sufficiency",
                prompt_ref=self._agent.sufficiency_prompt_ref,
                llm_call_increment=1,
            ),
        }
        if sufficiency_result["status"] == "NEEDS_MORE_DATA":
            next_state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = followup_planner_projection(
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                prior_query_attempts=list(state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])),
                unresolved_sufficiency_issues=cast(
                    list[dict[str, object]], list(sufficiency_result["issues"])
                ),
                read_result_summaries=self._bounded_read_result_summaries(state),
            )
        return next_state

    def _route_after_init(self, state: ContextRetrievalLocalState) -> str:
        # Q2-HANDOFF: an incoming RetrievalRequiredV1 always plans a fresh
        # query (never select_evidence-only), even though acquisition_result
        # already holds a prior invocation's reads -- there is no
        # invocation-local canonical plan left to run a CHANGED merge
        # against, so this is INITIAL-capable planning, not the local loop's
        # plan_followup.
        if state.get(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY) is not None:
            return "plan_query"
        return "select_evidence" if state.get("acquisition_result") is not None else "plan_query"

    def _route_after_plan_query(self, state: ContextRetrievalLocalState) -> str:
        return (
            "execute_followup_search"
            if state.get("acquisition_result") is not None
            else "execute_initial_read"
        )

    def _validated_task_container_refs(
        self, frozen_routes: list[InputToolRouteV1]
    ) -> dict[str, list[str]]:
        """TASK routes' only supported semantic constraint kind, resolved.

        Reuses the account's already-configured ``default_tasklist_id``
        Setting (the same authoritative source ``resource_queries.py``'s
        own ``_resolve_task_list_id`` falls back to) instead of adding a new
        discovery capability to the Retrieval read boundary. Empty when the
        provider is unset or returns ``None`` -- a TASK route then simply
        stays unable to satisfy CONTAINER_REF, exactly as before this fix.
        """
        if self._default_tasklist_id_provider is None:
            return {}
        default_tasklist_id = self._default_tasklist_id_provider()
        if not default_tasklist_id:
            return {}
        return {
            route["route_id"]: [default_tasklist_id]
            for route in frozen_routes
            if coarse_resource_category(route["resource_type"]) == "TASK"
        }

    def _plan_initial_query_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        validated_container_refs = self._validated_task_container_refs(frozen_routes)
        followup = state.get(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY)
        prompt_input = (
            initial_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=self._acquisition_agent.retrieval_budget,
                validated_container_refs=validated_container_refs,
            )
            if followup is None
            else followup_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=self._acquisition_agent.retrieval_budget,
                followup=followup,
                validated_container_refs=validated_container_refs,
            )
        )
        query_plan = self._retrieval_query_planner.plan(
            prompt_input=prompt_input,
            trace_context=_planner_trace_context(state),
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            validated_container_refs=validated_container_refs,
        )
        canonical_plans = self._source_fetch_plan_builder.build(
            query_plan,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=state.get(CONTEXT_SEGMENT_HANDLES_KEY, []),
        )
        return {
            **state,
            CONTEXT_CANONICAL_PLANS_KEY: {plan["route_id"]: plan for plan in canonical_plans},
            "source_fetch_plans": project_for_legacy_read_executor(
                canonical_plans,
                frozen_routes=frozen_routes,
                retrieval_budget=self._acquisition_agent.retrieval_budget,
            ),
        }

    def _execute_initial_read_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        result = self._acquisition_agent.acquire(
            plans=state["source_fetch_plans"],
            request=request_from_state(state),
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            tool_route_plan=_require_state_value(state.get("tool_route_plan"), "tool_route_plan"),
            read_result_cache=self._read_result_cache,
            read_handle_factory=self._id_factory,
        )
        next_state = {
            **state,
            "acquisition_result": result,
            CONTEXT_READ_RESULT_HANDLES_KEY: self._latest_read_handles(
                state, state["source_fetch_plans"]
            ),
            CONTEXT_SEGMENT_HANDLES_KEY: list(result["resource_handles"]),
            CONTEXT_QUERY_ATTEMPTS_KEY: self._append_read_attempts(
                state=state,
                result=result,
                plans=state["source_fetch_plans"],
                operation_kind="SEARCH",
                previous_query_hash=None,
            ),
        }
        return cast(ContextRetrievalLocalState, next_state)

    def _execute_followup_search_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        """Publish a changed SEARCH only after its complete read is materialized."""
        previous = _require_state_value(state["acquisition_result"], "acquisition_result")
        result = self._acquisition_agent.acquire(
            plans=state["source_fetch_plans"],
            request=request_from_state(state),
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            tool_route_plan=_require_state_value(state.get("tool_route_plan"), "tool_route_plan"),
            read_result_cache=self._read_result_cache,
            read_handle_factory=self._id_factory,
        )
        if result["status"] not in {"COMPLETE", "PARTIAL"}:
            return state
        combined = {
            **result,
            "resource_handles": cast(list[str], previous["resource_handles"])
            + cast(list[str], result["resource_handles"]),
            "source_summaries": cast(list[dict[str, object]], previous["source_summaries"])
            + cast(list[dict[str, object]], result["source_summaries"]),
        }
        # Q2-HANDOFF: reached via init->plan_query (external RetrievalRequiredV1
        # re-entry) rather than the local loop's assess_sufficiency->
        # plan_followup, _init_node already set CONTEXT_CURRENT_ROUND_NO_KEY to
        # this invocation's own round -- CONTEXT_FOLLOWUP_OPERATION_KEY (only
        # ever set by _plan_followup_node) distinguishes the two paths, so the
        # round is not double-counted.
        round_no = state[CONTEXT_CURRENT_ROUND_NO_KEY]
        if state.get(CONTEXT_FOLLOWUP_OPERATION_KEY) is not None:
            round_no += 1
        published_state = {
            **state,
            "acquisition_result": cast(Any, combined),
            CONTEXT_CURRENT_ROUND_NO_KEY: round_no,
            CONTEXT_READ_RESULT_HANDLES_KEY: self._latest_read_handles(
                state, state["source_fetch_plans"]
            ),
            CONTEXT_SEGMENT_HANDLES_KEY: [
                *state.get(CONTEXT_SEGMENT_HANDLES_KEY, []),
                *result["resource_handles"],
            ],
        }
        published_state[CONTEXT_QUERY_ATTEMPTS_KEY] = self._append_read_attempts(
            state=cast(ContextRetrievalLocalState, published_state),
            result=result,
            plans=state["source_fetch_plans"],
            operation_kind="SEARCH",
            previous_query_hash=None,
        )
        return cast(ContextRetrievalLocalState, published_state)

    def _route_after_sufficiency(self, state: ContextRetrievalLocalState) -> str:
        sufficiency = state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]
        if sufficiency["status"] != "NEEDS_MORE_DATA":
            return "finalize"
        if state[CONTEXT_CURRENT_ROUND_NO_KEY] >= 2:
            return "finalize"
        if state.get("tool_route_plan") is None:
            return "finalize"
        # Local continuation is possible only for an already completed read
        # in the same frozen route.  No parent retry signal is emitted.
        for plan in state.get("source_fetch_plans", []):
            route_id = _route_id_for_plan(state, plan)
            handle = self._read_result_cache.latest_handle(
                run_id=state["run_id"], route_id=route_id, query_hash=retrieval_query_hash(plan)
            )
            if handle is not None:
                return "plan_followup"
        return "finalize"

    def _plan_followup_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        validated_container_refs = self._validated_task_container_refs(frozen_routes)
        followup = _require_state_value(
            state.get(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY), "follow-up planner input"
        )
        detail_candidate_refs = state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])
        query_plan = self._retrieval_query_planner.plan(
            prompt_input=followup_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=self._acquisition_agent.retrieval_budget,
                followup=followup,
                validated_container_refs=validated_container_refs,
            ),
            trace_context=_planner_trace_context(state),
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
        prior_canonical = state.get(CONTEXT_CANONICAL_PLANS_KEY, {})
        prior_legacy = cast(list[Any], state.get("source_fetch_plans", []))
        handles = {
            _route_id_for_plan(state, plan): handle
            for plan in prior_legacy
            if (
                handle := self._read_result_cache.latest_handle(
                    run_id=state["run_id"],
                    route_id=_route_id_for_plan(state, plan),
                    query_hash=retrieval_query_hash(plan),
                )
            )
            is not None
        }
        try:
            canonical_plans = self._source_fetch_plan_builder.build(
                query_plan,
                frozen_routes=frozen_routes,
                route_policies=route_policies,
                prior_plans=prior_canonical,
                prior_read_result_handles=handles,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            )
        except Exception:
            return {**state, CONTEXT_FOLLOWUP_OPERATION_KEY: "FINALIZE"}
        operations = {plan["operation_kind"] for plan in canonical_plans}
        if operations == {"NEXT_PAGE"}:
            return {
                **state,
                CONTEXT_FOLLOWUP_OPERATION_KEY: "NEXT_PAGE",
                CONTEXT_NEXT_PAGE_HANDLES_KEY: {
                    plan["route_id"]: cast(str, plan["prior_read_result_handle"])
                    for plan in canonical_plans
                },
            }
        if operations in ({"SEARCH"}, {"FREEBUSY"}):
            try:
                legacy_plans = project_for_legacy_read_executor(
                    canonical_plans,
                    frozen_routes=frozen_routes,
                    retrieval_budget=self._acquisition_agent.retrieval_budget,
                )
            except Exception:
                return {**state, CONTEXT_FOLLOWUP_OPERATION_KEY: "FINALIZE"}
            return {
                **state,
                "source_fetch_plans": legacy_plans,
                CONTEXT_CANONICAL_PLANS_KEY: {plan["route_id"]: plan for plan in canonical_plans},
                CONTEXT_FOLLOWUP_OPERATION_KEY: "SEARCH",
            }
        if operations == {"DETAIL_FETCH"}:
            return {
                **state,
                CONTEXT_FOLLOWUP_OPERATION_KEY: "DETAIL_FETCH",
                CONTEXT_DETAIL_CANDIDATES_KEY: {
                    plan["route_id"]: cast(str, plan["detail_candidate_ref"])
                    for plan in canonical_plans
                },
            }
        return {**state, CONTEXT_FOLLOWUP_OPERATION_KEY: "FINALIZE"}

    @staticmethod
    def _route_after_followup_plan(state: ContextRetrievalLocalState) -> str:
        operation = state.get(CONTEXT_FOLLOWUP_OPERATION_KEY)
        if operation == "NEXT_PAGE":
            return "execute_next_page"
        if operation == "SEARCH":
            return "execute_followup_search"
        if operation == "DETAIL_FETCH":
            return "execute_detail"
        return "finalize"

    def _execute_detail_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        candidates = state.get(CONTEXT_DETAIL_CANDIDATES_KEY, {})
        for plan in state.get("source_fetch_plans", []):
            route_id = _route_id_for_plan(state, plan)
            candidate = candidates.get(route_id)
            if candidate is None:
                continue
            try:
                target = self._read_result_cache.resolve_detail_target(
                    run_id=state["run_id"], route_id=route_id, resource_handle=candidate
                )
                previous = _require_state_value(state["acquisition_result"], "acquisition_result")
                read_result = self._retrieval_read_executor.execute_detail(
                    plan=plan,
                    target=target,
                    context=self._retrieval_read_executor.build_context(
                        remaining_budget=dict(previous["remaining_budget"]),
                        allowed_read_tool_ids=allowed_read_tool_ids(
                            _require_state_value(state["tool_route_plan"], "tool_route_plan"),
                            source=plan["source"],
                        ),
                    ),
                )
                materialized = self._acquisition_agent.materialize_retrieval_read(
                    plan=plan,
                    request=request_from_state(state),
                    tool_route_plan=_require_state_value(
                        state["tool_route_plan"], "tool_route_plan"
                    ),
                    read_result=read_result,
                    read_result_cache=self._read_result_cache,
                    read_handle_factory=self._id_factory,
                )
            except (ReadResultContinuationError, PermissionError):
                return state
            except Exception:
                return state
            if not materialized.segment_handles:
                return state
            self._read_result_cache.mark_detail_complete(
                run_id=state["run_id"], route_id=route_id, resource_handle=candidate
            )
            followup = {
                "schema_version": 1,
                "status": "COMPLETE",
                "resource_handles": list(materialized.segment_handles),
                "source_summaries": [materialized.source_summary],
                "missing_slots": [],
                "remaining_budget": previous["remaining_budget"],
            }
            published = {
                **state,
                "acquisition_result": {
                    **followup,
                    "resource_handles": [
                        *cast(list[str], previous["resource_handles"]),
                        *cast(list[str], followup["resource_handles"]),
                    ],
                    "source_summaries": [
                        *cast(list[dict[str, object]], previous["source_summaries"]),
                        *cast(list[dict[str, object]], followup["source_summaries"]),
                    ],
                },
                CONTEXT_CURRENT_ROUND_NO_KEY: state[CONTEXT_CURRENT_ROUND_NO_KEY] + 1,
            }
            published[CONTEXT_QUERY_ATTEMPTS_KEY] = self._append_read_attempts(
                state=cast(ContextRetrievalLocalState, published),
                result=followup,
                plans=[plan],
                operation_kind="DETAIL_FETCH",
                previous_query_hash=None,
            )
            return cast(ContextRetrievalLocalState, published)
        return state

    def _execute_next_page_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        for plan in state.get("source_fetch_plans", []):
            route_id = _route_id_for_plan(state, plan)
            query_hash = retrieval_query_hash(plan)
            handle = state.get(CONTEXT_NEXT_PAGE_HANDLES_KEY, {}).get(route_id)
            if handle is None:
                continue
            try:
                previous = _require_state_value(state["acquisition_result"], "acquisition_result")
                read_result = self._retrieval_read_executor.execute_next_page(
                    plan=plan,
                    run_id=state["run_id"],
                    route_id=route_id,
                    query_hash=query_hash,
                    read_result_handle=handle,
                    context=self._retrieval_read_executor.build_context(
                        remaining_budget=dict(previous["remaining_budget"]),
                        allowed_read_tool_ids=allowed_read_tool_ids(
                            _require_state_value(state["tool_route_plan"], "tool_route_plan"),
                            source=plan["source"],
                        ),
                    ),
                )
                if read_result.error_code is not None:
                    return state
                materialized = self._acquisition_agent.materialize_retrieval_read(
                    plan=plan,
                    request=request_from_state(state),
                    tool_route_plan=_require_state_value(
                        state["tool_route_plan"], "tool_route_plan"
                    ),
                    read_result=read_result,
                    read_result_cache=self._read_result_cache,
                    read_handle_factory=self._id_factory,
                )
            except ReadResultContinuationError:
                continue
            except Exception:
                # A provider read has no rollback.  Nothing semantic is
                # published unless the following materialization succeeded.
                return state
            if not materialized.segment_handles:
                return state
            followup = {
                "schema_version": 1,
                "status": "COMPLETE",
                "resource_handles": list(materialized.segment_handles),
                "source_summaries": [materialized.source_summary],
                "missing_slots": [],
                "remaining_budget": cast(dict[str, int], previous["remaining_budget"]),
            }
            combined = {
                **followup,
                "resource_handles": cast(list[str], previous["resource_handles"])
                + cast(list[str], followup["resource_handles"]),
                "source_summaries": cast(list[dict[str, object]], previous["source_summaries"])
                + cast(list[dict[str, object]], followup["source_summaries"]),
            }
            published_state = {
                **state,
                "acquisition_result": cast(Any, combined),
                CONTEXT_CURRENT_ROUND_NO_KEY: state[CONTEXT_CURRENT_ROUND_NO_KEY] + 1,
                CONTEXT_READ_RESULT_HANDLES_KEY: [
                    *state.get(CONTEXT_READ_RESULT_HANDLES_KEY, []),
                    materialized.read_result_handle,
                ],
                CONTEXT_SEGMENT_HANDLES_KEY: [
                    *state.get(CONTEXT_SEGMENT_HANDLES_KEY, []),
                    *materialized.segment_handles,
                ],
            }
            published_state[CONTEXT_QUERY_ATTEMPTS_KEY] = self._append_read_attempts(
                state=cast(ContextRetrievalLocalState, published_state),
                result=followup,
                plans=[plan],
                operation_kind="NEXT_PAGE",
                previous_query_hash=query_hash,
            )
            return cast(ContextRetrievalLocalState, published_state)
        return state

    def _finalize_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        sufficiency = state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]
        llm_provider_result = _require_state_value(
            state.get("llm_provider_result"), "llm_provider_result"
        )
        result = validate_context_retrieval_result_v1(
            self._agent.build_result_from_outputs(
                selection_result=selection,
                sufficiency_result=sufficiency,
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
                llm_provider_result=llm_provider_result,
            )
        )
        # Q2-HANDOFF: RetrievalResultV1 is only materialized for a disposition
        # a Parent may actually consume (SUFFICIENT/PARTIAL). Unfinished
        # candidates (NEEDS_MORE_DATA/NEEDS_CONFIRMATION/
        # ROUTE_RECONSIDERATION_REQUIRED/BLOCKED) are never forced into it --
        # Supervisor routes those purely on `disposition` below.
        retrieval_result = None
        if state.get("tool_route_plan") is not None and result["status"] in {
            "SUFFICIENT",
            "PARTIAL",
        }:
            retrieval_result = finalize_retrieval_result(
                artifact_id=self._id_factory(),
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                tool_route_plan=_require_state_value(state["tool_route_plan"], "tool_route_plan"),
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
                selection_result=selection,
                evidence_drafts=state["evidence_drafts"],
                sufficiency_result=sufficiency,
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
            )
        self._evidence_store.put(run_id=state["run_id"], evidence_drafts=state["evidence_drafts"])
        retrieval_return: RetrievalRouteResultV1 = {
            "disposition": cast(str, result["status"]),
            "typed_result": retrieval_result,
        }
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=retrieval_return,
            legacy_retrieval_result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="context_retriever",
                    agent_role="context_retriever",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="context",
                    node_name="finalize",
                ),
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(CONTEXT_AGENT_LOCAL_KEY, None)
        merged.pop(CONTEXT_RAG_CANDIDATES_KEY, None)
        merged.pop(CONTEXT_SELECTION_OUTPUT_KEY, None)
        merged.pop(CONTEXT_SUFFICIENCY_OUTPUT_KEY, None)
        merged.pop(CONTEXT_CURRENT_ROUND_NO_KEY, None)
        merged.pop(CONTEXT_READ_RESULT_HANDLES_KEY, None)
        merged.pop(CONTEXT_SEGMENT_HANDLES_KEY, None)
        merged.pop(CONTEXT_QUERY_ATTEMPTS_KEY, None)
        merged.pop(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY, None)
        merged.pop(CONTEXT_CANONICAL_PLANS_KEY, None)
        merged.pop(CONTEXT_FOLLOWUP_OPERATION_KEY, None)
        merged.pop(CONTEXT_NEXT_PAGE_HANDLES_KEY, None)
        merged.pop(CONTEXT_DETAIL_CANDIDATES_KEY, None)
        merged.pop("evidence_drafts", None)
        merged.pop("llm_provider_result", None)
        return cast(ContextRetrievalLocalState, merged)

    def _append_read_attempts(
        self,
        *,
        state: ContextRetrievalLocalState,
        result: Any,
        plans: list[Any],
        operation_kind: str,
        previous_query_hash: str | None,
    ) -> list[QueryAttempt]:
        attempts = cast(list[QueryAttempt], list(state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])))
        summaries = result["source_summaries"]
        for plan, summary in zip(plans, summaries, strict=False):
            route_id = _route_id_for_plan(state, plan)
            query_hash = retrieval_query_hash(plan)
            handle = self._read_result_cache.latest_handle(
                run_id=state["run_id"], route_id=route_id, query_hash=query_hash
            )
            page_state_hash = None
            if handle is not None:
                page_state_hash = self._read_result_cache.bounded_summary(
                    run_id=state["run_id"], handle=handle
                )["page_state_hash"]
            attempts.append(
                build_query_attempt(
                    query_attempt_id=self._id_factory(),
                    run_id=state["run_id"],
                    route_id=route_id,
                    round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                    attempt_no=len(attempts),
                    plan=plan,
                    connector_id=_connector_id_for_route(state, route_id),
                    operation_kind=cast(Any, operation_kind),
                    query_hash=query_hash,
                    previous_query_hash=previous_query_hash,
                    page_state_hash=cast(str | None, page_state_hash),
                    candidate_count=cast(int, summary["resource_count"]),
                    stop_reason="READ_COMPLETE",
                )
            )
        return attempts

    def _latest_read_handles(
        self, state: ContextRetrievalLocalState, plans: list[Any]
    ) -> list[str]:
        handles: list[str] = []
        for plan in plans:
            handle = self._read_result_cache.latest_handle(
                run_id=state["run_id"],
                route_id=_route_id_for_plan(state, plan),
                query_hash=retrieval_query_hash(plan),
            )
            if handle is not None:
                handles.append(handle)
        return handles

    def _bounded_read_result_summaries(
        self, state: ContextRetrievalLocalState
    ) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        for plan in state.get("source_fetch_plans", []):
            route_id = _route_id_for_plan(state, plan)
            handle = self._read_result_cache.latest_handle(
                run_id=state["run_id"],
                route_id=route_id,
                query_hash=retrieval_query_hash(plan),
            )
            if handle is not None:
                summaries.append(
                    self._read_result_cache.bounded_summary(run_id=state["run_id"], handle=handle)
                )
        return summaries


def _route_id_for_plan(state: ContextRetrievalLocalState, plan: Any) -> str:
    route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
    source = cast(str, plan["source"])
    category = {"GMAIL": "GMAIL", "TASKS": "TASK", "CALENDAR": "CALENDAR"}[source]
    for route in route_plan["input_plan"]["input_routes"]:
        if category in route["resource_type"]:
            return route["route_id"]
    raise ValueError("source is outside frozen input route")


def _connector_id_for_route(state: ContextRetrievalLocalState, route_id: str) -> str:
    route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
    for route in route_plan["input_plan"]["input_routes"]:
        if route["route_id"] == route_id:
            return route["connector_id"]
    raise ValueError("input route is missing")


def _retrieval_required_signal(signal: object) -> RetrievalRequiredV1 | None:
    if isinstance(signal, dict) and signal.get("kind") == "RETRIEVAL_REQUIRED":
        return cast(RetrievalRequiredV1, signal)
    return None


def _needs_as_sufficiency_issues(needs: list[RetrievalNeedV1]) -> list[dict[str, object]]:
    """Project an incoming WorkAnalysis/Review need into the same bounded,
    Retrieval-local ``unresolved_sufficiency_issues`` shape the internal
    local loop already feeds ``retrieval.plan_query`` with (SufficiencyIssue,
    docs/05-context-retrieval.md SS19.1) -- reusing the existing follow-up
    channel rather than adding a second, differently-shaped planner input."""
    return [
        {
            "slot": need["required_information"],
            "issue_type": "MISSING",
            "required": True,
            "resolution_source": "GOOGLE",
            "safety_critical": False,
            "reason_codes": list(need["reason_codes"]),
        }
        for need in needs
    ]
