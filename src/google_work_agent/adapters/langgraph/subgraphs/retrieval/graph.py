"""Canonical Retrieval LangGraph subgraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.state import (
    CONTEXT_AGENT_LOCAL_KEY,
    CONTEXT_CANONICAL_PLANS_KEY,
    CONTEXT_CURRENT_ROUND_NO_KEY,
    CONTEXT_DETAIL_CANDIDATES_KEY,
    CONTEXT_FOLLOWUP_OPERATION_KEY,
    CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY,
    CONTEXT_NEXT_PAGE_HANDLES_KEY,
    CONTEXT_QUERY_ATTEMPTS_KEY,
    CONTEXT_RAG_CANDIDATES_KEY,
    CONTEXT_READ_BINDINGS_KEY,
    CONTEXT_READ_RESULT_HANDLES_KEY,
    CONTEXT_SEGMENT_HANDLES_KEY,
    CONTEXT_SELECTION_OUTPUT_KEY,
    CONTEXT_SUFFICIENCY_OUTPUT_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    ContextRetrievalInputState,
    ContextRetrievalLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.assess_sufficiency_node import (
    assess_sufficiency_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.build_query_node import (
    build_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.finalize_retrieval_node import (
    finalize_retrieval_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.normalize_segments_node import (
    normalize_segments_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.plan_query_node import (
    plan_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.rag_retrieve_rerank_node import (  # noqa: E501
    rag_retrieve_rerank_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.select_evidence_node import (
    select_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.execute_read_projection import (  # noqa: E501
    find_detail_resource,
    project_acquisition_result,
    project_connector_call,
    sanitize_acquisition_result,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_assess_sufficiency import (  # noqa: E501
    route_after_assess_sufficiency,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_finalize_retrieval import (  # noqa: E501
    route_after_finalize_retrieval,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_select_evidence import (  # noqa: E501
    route_after_select_evidence,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.state import RetrievalStateV2
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.execute_read import RetrievalReadBindingError
from google_work_agent.application.agents.retrieval.resolve_availability import (
    AvailableIntervalV1,
    BusyIntervalV1,
    resolve_availability,
)
from google_work_agent.application.agents.retrieval.select_evidence import (
    materialize_evidence_drafts,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.confirmation import (
    build_user_interrupt_v1,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ClarificationQuestionV1,
    RequestIntentV2,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.retrieval_attempts import (
    build_query_attempt,
    followup_planner_projection,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.orchestration.retrieval_planner_input import (
    DEFAULT_RETRIEVAL_BUDGET,
    followup_retrieval_planner_input,
    initial_retrieval_planner_input,
)
from google_work_agent.application.orchestration.retrieval_query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.orchestration.retrieval_rounds import (
    initialize_current_round_no,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    SourceFetchPlanV1 as CanonicalSourceFetchPlanV1,
)
from google_work_agent.application.orchestration.supervisor import (
    RetrievalRouteResultV1,
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ContextRetrievalLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


def _resolve_availability_from_reads(
    *,
    acquisition_result: AcquisitionResultV1,
    canonical_plans: Mapping[str, CanonicalSourceFetchPlanV1],
) -> list[AvailableIntervalV1]:
    """Project FreeBusy reads into provider-neutral availability Local State."""
    freebusy_resources = [
        (str(summary.get("route_id", "")), resource)
        for summary in acquisition_result["source_summaries"]
        for resource in cast(list[dict[str, object]], summary.get("resources", []))
        if resource.get("resource_type") == "calendar_freebusy"
    ]
    if not freebusy_resources:
        return []
    results: list[AvailableIntervalV1] = []
    for route_id, resource in freebusy_resources:
        plan = canonical_plans.get(route_id)
        if plan is None:
            raise ValueError("FreeBusy result has no canonical source plan")
        timezones = {
            str(constraint["timezone"])
            for constraint in plan["effective_constraints"]
            if constraint["kind"] == "TEMPORAL_RANGE"
        }
        if len(timezones) != 1:
            raise ValueError("FreeBusy availability requires one frozen calendar timezone")
        timezone = next(iter(timezones))
        handle = resource.get("resource_handle")
        payload = resource.get("payload")
        if not isinstance(handle, str) or not isinstance(payload, Mapping):
            raise ValueError("FreeBusy resource projection is invalid")
        window_start = payload.get("time_min")
        window_end = payload.get("time_max")
        raw_intervals = payload.get("busy_intervals", [])
        if (
            not isinstance(window_start, str)
            or not isinstance(window_end, str)
            or not isinstance(raw_intervals, list)
        ):
            raise ValueError("FreeBusy interval projection is invalid")
        busy_intervals: list[BusyIntervalV1] = []
        for interval in raw_intervals:
            if not isinstance(interval, Mapping):
                raise ValueError("FreeBusy busy interval must be an object")
            start = interval.get("start")
            end = interval.get("end")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("FreeBusy busy interval boundaries are invalid")
            busy_intervals.append({"start": start, "end": end, "resource_ref": handle})
        results.extend(
            resolve_availability(
                window_start=window_start,
                window_end=window_end,
                timezone=timezone,
                busy_intervals=busy_intervals,
            )
        )
    return results


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
                and "gmail_search_threads" in route["allowed_read_tool_ids"]
                else frozenset()
            ),
        )
        for route in routes
        if coarse_resource_category(route["resource_type"]) in supported_by_resource
    }


def _retrieval_trace_context(
    state: ContextRetrievalLocalState, node_id: str
) -> ObservabilityContext:
    request = request_from_state(state)
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=f"{request.run_id}:{node_id}",
    )


class RetrievalSubgraph:
    """Build and execute the canonical Retrieval runtime."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_manifest_path: Path | None,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: Callable[[str, str], None],
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        connector_reader: ConnectorReadPort,
        tool_catalog: SignedToolRegistry,
        read_result_cache: RunRetrievalCachePort,
        confirm_inline: ConfirmInline,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._plan_query_prompt_ref = load_prompt_reference("retrieval.plan_query", manifest_path)
        self._select_prompt_ref = load_prompt_reference("retrieval.select_evidence", manifest_path)
        self._sufficiency_prompt_ref = load_prompt_reference(
            "retrieval.assess_sufficiency", manifest_path
        )
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._connector_reader = connector_reader
        self._tool_catalog = tool_catalog
        self._read_result_cache = read_result_cache
        self._confirm_inline = confirm_inline
        # Pre-Prompt Runtime Closure: TASK routes' only supported semantic
        # constraint kind is CONTAINER_REF (_runtime_route_constraint_policies
        # below), but nothing ever populated validated_container_refs for the
        # planner call, so a TASK-resource plan_query could never validate.
        # Reuses the existing per-account Settings default_tasklist_id
        # concept (already the authoritative resource handler access layer's
        # own _resolve_task_list_id falls back to) rather than adding a new
        # discovery Port/authority. When unset, TASK routes keep today's
        # existing (pre-existing, unrelated to this change) behavior.
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._default_calendar_id_provider = default_calendar_id_provider

    def build(self) -> Any:
        graph = StateGraph(
            ContextRetrievalLocalState,
            input_schema=ContextRetrievalInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("plan_query", self._plan_query_node)
        graph.add_node("build_query", self._build_query_node)
        graph.add_node("execute_read", self._execute_read_node)
        graph.add_node("normalize_segments", self._normalize_segments_node)
        graph.add_node("rag_retrieve", self._rag_retrieve_node)
        graph.add_node("select_evidence", self._select_evidence_node)
        graph.add_node("assess_sufficiency", self._assess_sufficiency_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "plan_query")
        graph.add_edge("plan_query", "build_query")
        graph.add_conditional_edges(
            "build_query",
            self._route_after_build_query,
            {"execute_read": "execute_read", "finalize": "finalize"},
        )
        graph.add_edge("execute_read", "normalize_segments")
        graph.add_edge("normalize_segments", "rag_retrieve")
        graph.add_edge("rag_retrieve", "select_evidence")
        graph.add_conditional_edges(
            "select_evidence",
            route_after_select_evidence,
            {"assess_sufficiency": "assess_sufficiency"},
        )
        graph.add_conditional_edges(
            "assess_sufficiency",
            self._route_after_sufficiency,
            {"plan_query": "plan_query", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="retrieval_subgraph")

    @staticmethod
    def _route_after_finalize(state: ContextRetrievalLocalState) -> str:
        if state.get("__context_retrieval_retry_confirmation__"):
            return "finalize"
        if state.get("retrieval_result") is not None:
            return route_after_finalize_retrieval({"final_result": state["retrieval_result"]})
        return "end"

    def _initialize_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        invocation_id = self._id_factory()
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        current_round_no = initialize_current_round_no(
            prior_result=state.get("retrieval_result"),
            tool_route_plan=tool_route_plan,
        )
        local_state = build_agent_local_state(
            agent_role="context_retriever",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "has_prior_acquisition": state.get("acquisition_result") is not None,
            },
            prompt_ref=self._select_prompt_ref,
        )
        next_state: ContextRetrievalLocalState = {
            **state,
            "input_route_ref": cast(
                StateArtifactRefV1, dict(tool_route_plan["input_plan"]["meta"])
            ),
            "input_routes": list(tool_route_plan["input_plan"]["input_routes"]),
            "query_plan": None,
            "query_attempts": [],
            "source_statuses": [],
            "read_result_handles": [],
            "segment_handles": [],
            "availability_results": [],
            "rag_candidates": [],
            "evidence_selection": None,
            "sufficiency": None,
            "final_result": None,
            CONTEXT_AGENT_LOCAL_KEY: local_state,
            CONTEXT_CURRENT_ROUND_NO_KEY: current_round_no,
            CONTEXT_READ_RESULT_HANDLES_KEY: [],
            CONTEXT_READ_BINDINGS_KEY: {},
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
                prompt_ref=self._select_prompt_ref,
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
        pending_need = _pending_retrieval_need(state.get("pending_user_retrieval_need"))
        if retrieval_required is not None or pending_need is not None:
            next_state["workflow_signal"] = None
            needs = (
                retrieval_required["needs"]
                if retrieval_required is not None
                else [cast(RetrievalNeedV1, pending_need)]
            )
            next_state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = followup_planner_projection(
                current_round_no=current_round_no,
                prior_query_attempts=[],
                unresolved_sufficiency_issues=_needs_as_sufficiency_issues(needs),
                read_result_summaries=self._bounded_read_result_summaries(next_state),
            )
        return next_state

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._normalized_segments(state)
        rag_candidates = _require_state_value(
            state.get(CONTEXT_RAG_CANDIDATES_KEY), "rag candidates"
        )
        ensure_llm_call_budget(state)
        patch = select_evidence_node(
            cast(
                RetrievalStateV2,
                {
                    "request_intent": request_intent,
                    "rag_candidates": rag_candidates,
                    "exclusion_obligation_segment_ids": state.get(
                        "exclusion_obligation_segment_ids", []
                    ),
                },
            ),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._select_prompt_ref,
            revision_prompt_ref=self._select_prompt_ref,
            trace_context=_retrieval_trace_context(state, "retrieval.select_evidence"),
            segments=cast(list[Any], segments),
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
        )
        selection = cast(Any, patch["evidence_selection"])
        revised_retry_budget = cast(RunBudgetV2, patch["retry_budget"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECT_EVIDENCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        selected_state = cast(
            ContextRetrievalLocalState,
            {
                **state,
                CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                CONTEXT_RAG_CANDIDATES_KEY: rag_candidates,
                CONTEXT_SELECTION_OUTPUT_KEY: selection,
                "rag_candidates": rag_candidates,
                "evidence_selection": selection,
                "retry_budget": consume_llm_call_budget(
                    {**state, "retry_budget": revised_retry_budget}, provider_calls_consumed=1
                ),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="context_retriever",
                    agent_role="context_retriever",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="context",
                    node_name="select_evidence",
                    llm_call_id=f"{request.run_id}:retrieval.select_evidence",
                    prompt_ref=self._select_prompt_ref,
                    llm_call_increment=1,
                ),
            },
        )
        return self._materialize_evidence(selected_state)

    def _normalize_segments_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        working_state = self._ephemeral_raw_state(state)
        acquisition_result = _require_state_value(
            working_state["acquisition_result"], "acquisition_result"
        )
        patch = normalize_segments_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "normalize_segments": {"acquisition_result": acquisition_result}
                    }
                },
            )
        )
        segments = cast(list[Any], patch["normalized_segments"])
        return cast(
            ContextRetrievalLocalState,
            {
                **state,
                "acquisition_result": sanitize_acquisition_result(acquisition_result),
                "segments": [segment.segment_id for segment in segments],
                "segment_handles": list(state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])),
                "availability_results": _resolve_availability_from_reads(
                    acquisition_result=acquisition_result,
                    canonical_plans=state.get(CONTEXT_CANONICAL_PLANS_KEY, {}),
                ),
            },
        )

    def _normalized_segments(self, state: ContextRetrievalLocalState) -> list[Any]:
        working_state = self._ephemeral_raw_state(state)
        acquisition_result = _require_state_value(
            working_state["acquisition_result"], "acquisition_result"
        )
        patch = normalize_segments_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "normalize_segments": {"acquisition_result": acquisition_result}
                    }
                },
            )
        )
        segments = cast(list[Any], patch["normalized_segments"])
        expected_ids = state.get("segments")
        actual_ids = [segment.segment_id for segment in segments]
        if expected_ids is not None and actual_ids != expected_ids:
            raise ValueError("stable segment identity changed within one retrieval round")
        return segments

    def _ephemeral_raw_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        handles = cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, []))
        bindings = cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        if not handles:
            return state
        results = self._resolve_cached_results(state, bindings=bindings, handles=handles)
        plans = self._plans_for_cached_results(
            state,
            plans=cast(list[CanonicalSourceFetchPlanV1], state.get("source_fetch_plans", [])),
            bindings=bindings,
            handles=handles,
        )
        safe = cast(AcquisitionResultV1, state.get("acquisition_result"))
        hydrated = project_acquisition_result(
            list(zip(plans, results, strict=True)),
            remaining_budget=dict(safe["remaining_budget"]),
        )
        return cast(
            ContextRetrievalLocalState,
            {**state, "acquisition_result": hydrated},
        )

    def _rag_retrieve_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._normalized_segments(state)
        patch = rag_retrieve_rerank_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "rag_retrieve_rerank": {
                            "segments": cast(list[Any], segments),
                            "request_intent": request_intent,
                            "top_k": 24,
                        }
                    }
                },
            )
        )
        candidates = cast(list[Any], patch["rag_candidates"])
        return {
            **state,
            "ranked_segments": candidates,
            "rag_candidates": candidates,
            CONTEXT_RAG_CANDIDATES_KEY: candidates,
        }

    def _materialize_evidence(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        evidence_drafts = materialize_evidence_drafts(
            selection,
            segments=cast(list[Any], self._normalized_segments(state)),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECTION_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "evidence_drafts": evidence_drafts,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="select_evidence",
            ),
        }

    def _run_sufficiency_attempt(
        self,
        state: ContextRetrievalLocalState,
        *,
        confirmation_response: ConfirmationResponseProjectionV1 | None,
    ) -> tuple[SufficiencyResultV2, dict[str, object], RunBudgetV2]:
        """One ``retrieval.assess_sufficiency`` LLM call. Safe to call again
        for a later confirmation round -- ``select_evidence``/
        deterministic evidence materialization already completed before any
        pause, so ``evidence_drafts`` here is always the same already-frozen
        selection, never re-derived or re-fetched.
        """
        ensure_llm_call_budget(state)
        patch = assess_sufficiency_node(
            cast(
                RetrievalStateV2,
                {
                    "request_intent": _require_state_value(
                        state["request_intent"], "request_intent"
                    ),
                    "evidence_selection": state[CONTEXT_SELECTION_OUTPUT_KEY],
                },
            ),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._sufficiency_prompt_ref,
            trace_context=_retrieval_trace_context(state, "retrieval.assess_sufficiency"),
            tool_route_plan=state.get("tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            evidence_drafts=state["evidence_drafts"],
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
            confirmation_response=confirmation_response,
        )
        sufficiency_result = cast(SufficiencyResultV2, patch["sufficiency"])
        llm_provider_result: dict[str, object] = {"structured_output_attempts": 1}
        retry_budget = consume_llm_call_budget(
            state,
            provider_calls_consumed=cast(int, llm_provider_result["structured_output_attempts"]),
        )
        return sufficiency_result, llm_provider_result, retry_budget

    def _assess_sufficiency_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        sufficiency_result, llm_provider_result, retry_budget = self._run_sufficiency_attempt(
            state, confirmation_response=None
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SUFFICIENCY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], sufficiency_result)
        next_state: ContextRetrievalLocalState = {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
            "sufficiency": sufficiency_result,
            "llm_provider_result": llm_provider_result,
            "retry_budget": retry_budget,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="assess_sufficiency",
                llm_call_id=f"{request_from_state(state).run_id}:retrieval.assess_sufficiency",
                prompt_ref=self._sufficiency_prompt_ref,
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
        elif sufficiency_result["status"] == "NEEDS_CONFIRMATION":
            # Materialized here -- not in finalize -- because this node never
            # replays on resume (it completes and commits before any pause),
            # so interrupt_id is generated exactly once and stays stable
            # across finalize's node-replay.
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                result=sufficiency_result, request_intent=request_intent
            )
            next_state["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            next_state["user_interrupt"] = cast(Any, user_interrupt)
            next_state["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": confirmation_interrupt,
            }
        return next_state

    @staticmethod
    def _route_after_build_query(state: ContextRetrievalLocalState) -> str:
        return (
            "finalize"
            if state.get(CONTEXT_FOLLOWUP_OPERATION_KEY) == "FINALIZE"
            else "execute_read"
        )

    def _validated_container_refs(
        self, frozen_routes: list[InputToolRouteV1]
    ) -> dict[str, list[str]]:
        """TASK routes' only supported semantic constraint kind, resolved.

        Reuses the account's already-configured ``default_tasklist_id``
        Setting (the same authoritative resource access layer's
        own ``_resolve_task_list_id`` falls back to) instead of adding a new
        discovery capability to the Retrieval read boundary. Empty when the
        provider is unset or returns ``None`` -- a TASK route then simply
        stays unable to satisfy CONTAINER_REF, exactly as before this fix.
        """
        tasklist_id = (
            None
            if self._default_tasklist_id_provider is None
            else self._default_tasklist_id_provider()
        )
        calendar_id = (
            None
            if self._default_calendar_id_provider is None
            else self._default_calendar_id_provider()
        )
        result: dict[str, list[str]] = {}
        for route in frozen_routes:
            category = coarse_resource_category(route["resource_type"])
            if category == "TASK" and tasklist_id:
                result[route["route_id"]] = [tasklist_id]
            elif category == "CALENDAR" and calendar_id:
                result[route["route_id"]] = [calendar_id]
        return result

    @staticmethod
    def _validated_resource_refs(
        state: ContextRetrievalLocalState,
        frozen_routes: list[InputToolRouteV1],
    ) -> dict[str, list[str]]:
        """Bind current-Run selected identities only to exact direct-read routes."""
        selected_refs = request_from_state(state).selected_resources
        direct_read_tools = {
            "gmail_get_thread",
            "gmail_get_message",
            "gmail_get_draft",
            "gmail_get_attachment",
            "tasks_get_task",
            "calendar_get_event",
        }
        result: dict[str, list[str]] = {}
        for route in frozen_routes:
            if not direct_read_tools.intersection(route["allowed_read_tool_ids"]):
                continue
            route_type = route["resource_type"].upper()
            refs: list[str] = []
            for item in selected_refs:
                selected_type = f"{item.source}_{item.resource_type}".upper()
                selected_type = {
                    "TASKS_TASK": "TASK",
                    "TASKS_TASK_LIST": "TASK_LIST",
                    "CALENDAR_CALENDAR": "CALENDAR",
                    "CALENDAR_EVENT": "CALENDAR_EVENT",
                    "CALENDAR_FREEBUSY": "CALENDAR_FREEBUSY",
                }.get(selected_type, selected_type)
                if selected_type == route_type:
                    refs.append(f"{route_type.lower()}:{item.resource_id}")
            if refs:
                result[route["route_id"]] = refs
        return result

    @staticmethod
    def _selected_detail_resource(
        state: ContextRetrievalLocalState,
        *,
        resource_type: str,
        resource_ref: str,
    ) -> Mapping[str, object] | None:
        for item in request_from_state(state).selected_resources:
            if resource_ref != f"{resource_type.lower()}:{item.resource_id}":
                continue
            return {
                "resource_type": resource_type.lower(),
                "resource_id": item.resource_id,
                "parent_id": item.parent_resource_id,
            }
        return None

    def _plan_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        if CONTEXT_AGENT_LOCAL_KEY not in state:
            state = self._initialize_state(state)
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        validated_resource_refs = self._validated_resource_refs(state, frozen_routes)
        validated_container_refs = self._validated_container_refs(frozen_routes)
        followup = state.get(CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY)
        prompt_input = (
            initial_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=DEFAULT_RETRIEVAL_BUDGET,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
            if followup is None
            else followup_retrieval_planner_input(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                input_routes=frozen_routes,
                retrieval_budget=DEFAULT_RETRIEVAL_BUDGET,
                followup=followup,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
        )
        ensure_llm_call_budget(state)
        patch = plan_query_node(
            cast(
                Any,
                {
                    "operation_inputs": {
                        "plan_query": {
                            "llm_runtime": self._llm_runtime,
                            "prompt_ref": self._plan_query_prompt_ref,
                            "revision_prompt_ref": self._plan_query_prompt_ref,
                            "output_schema": RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
                            "prompt_input": prompt_input,
                            "trace_context": _retrieval_trace_context(
                                state, "retrieval.plan_query"
                            ),
                            "frozen_routes": frozen_routes,
                            "route_policies": route_policies,
                            "retry_budget": cast(RunBudgetV2, state["retry_budget"]),
                            "validated_resource_refs": validated_resource_refs,
                            "validated_container_refs": validated_container_refs,
                            "detail_candidate_refs": state.get(CONTEXT_SEGMENT_HANDLES_KEY, []),
                        }
                    }
                },
            )
        )
        query_plan = patch["query_plan"]
        revised_retry_budget = cast(RunBudgetV2, patch["retry_budget"])
        return {
            **state,
            "query_plan": query_plan,
            "retry_budget": consume_llm_call_budget(
                {**state, "retry_budget": revised_retry_budget}, provider_calls_consumed=1
            ),
        }

    def _execute_read_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        plans = cast(
            list[CanonicalSourceFetchPlanV1],
            list(state.get("source_fetch_plans", [])),
        )
        route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        routes = {route["route_id"]: route for route in route_plan["input_plan"]["input_routes"]}
        bindings = dict(cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {})))
        prior_results = self._resolve_cached_results(state, bindings=bindings)
        new_handles: list[str] = []
        attempts = list(cast(list[QueryAttemptV1], state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])))
        for plan in plans:
            route = routes.get(plan["route_id"])
            if route is None:
                raise RetrievalReadBindingError("retrieval plan route is not frozen")
            detail_resource = None
            candidate_ref = plan["detail_candidate_ref"]
            if candidate_ref is not None:
                detail_resource = find_detail_resource(candidate_ref, prior_results)
                if detail_resource is None:
                    raise RetrievalReadBindingError("DETAIL_FETCH candidate is not cache-bound")
            resource_refs = [
                ref
                for constraint in plan["effective_constraints"]
                if constraint["kind"] == "RESOURCE_REF"
                for ref in constraint["resource_refs"]
            ]
            if resource_refs:
                if len(resource_refs) != 1:
                    raise RetrievalReadBindingError(
                        "direct selected-resource read requires exactly one resource ref"
                    )
                detail_resource = self._selected_detail_resource(
                    state,
                    resource_type=plan["resource_type"],
                    resource_ref=resource_refs[0],
                )
                if detail_resource is None:
                    raise RetrievalReadBindingError("selected resource is not current-Run bound")
            tool_id, arguments = project_connector_call(
                plan,
                route=route,
                page_size=DEFAULT_RETRIEVAL_BUDGET.max_page_size,
                detail_resource=detail_resource,
            )
            binding = self._tool_catalog.bind_required(plan["connector_id"], tool_id, "READ")
            read_handle = self._id_factory()
            patch = execute_read_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "execute_read": {
                                "plan": plan,
                                "run_id": state["run_id"],
                                "binding": binding,
                                "tool_arguments": arguments,
                                "connector_reader": self._connector_reader,
                                "read_result_cache": self._read_result_cache,
                                "read_result_handle": read_handle,
                            }
                        }
                    },
                )
            )
            execution = cast(Any, patch["read_execution"])
            effective_handle = execution.read_result_handle
            if execution.status == "COMPLETE":
                bindings[effective_handle] = {
                    "route_id": plan["route_id"],
                    "query_identity_hash": plan["query_identity_hash"],
                }
                new_handles.append(effective_handle)
            token = None
            resolution = self._read_result_cache.resolve_read_result(
                effective_handle,
                state["run_id"],
                plan["route_id"],
                plan["query_identity_hash"],
            )
            if resolution.entry is not None:
                token = resolution.entry.read_result.next_page_token
            attempts.append(
                build_query_attempt(
                    query_attempt_id=self._id_factory(),
                    run_id=state["run_id"],
                    plan=plan,
                    round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                    attempt_no=len(attempts),
                    tool_id=tool_id,
                    canonical_arguments=arguments,
                    previous_query_hash=(
                        None
                        if plan["prior_read_result_handle"] is None
                        else plan["query_identity_hash"]
                    ),
                    page_state_hash=(None if token is None else sha256(token.encode()).hexdigest()),
                    candidate_count=execution.total_count,
                    stop_reason=execution.status,
                )
            )
        all_handles = [
            *cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])),
            *new_handles,
        ]
        raw_results = self._resolve_cached_results(
            state,
            bindings=bindings,
            handles=all_handles,
        )
        plan_by_binding = self._plans_for_cached_results(
            state, plans=plans, bindings=bindings, handles=all_handles
        )
        acquisition = project_acquisition_result(
            list(zip(plan_by_binding, raw_results, strict=True)),
            remaining_budget=self._remaining_retrieval_budget(state, len(new_handles)),
        )
        prior_round = state[CONTEXT_CURRENT_ROUND_NO_KEY]
        round_no = prior_round + (1 if state.get(CONTEXT_FOLLOWUP_OPERATION_KEY) else 0)
        safe_acquisition = self._bounded_acquisition(acquisition)
        return cast(
            ContextRetrievalLocalState,
            {
                **state,
                "acquisition_result": safe_acquisition,
                CONTEXT_CURRENT_ROUND_NO_KEY: round_no,
                CONTEXT_READ_RESULT_HANDLES_KEY: all_handles,
                CONTEXT_SEGMENT_HANDLES_KEY: list(acquisition["resource_handles"]),
                CONTEXT_QUERY_ATTEMPTS_KEY: attempts,
                CONTEXT_READ_BINDINGS_KEY: bindings,
                "read_result_handles": all_handles,
                "segment_handles": list(acquisition["resource_handles"]),
                "query_attempts": attempts,
            },
        )

    def _resolve_cached_results(
        self,
        state: ContextRetrievalLocalState,
        *,
        bindings: Mapping[str, object],
        handles: list[str] | None = None,
    ) -> list[Any]:
        resolved = []
        for handle in handles or cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])):
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping):
                raise RetrievalReadBindingError("read-result handle has no local binding")
            route_id = raw.get("route_id")
            query_hash = raw.get("query_identity_hash")
            if not isinstance(route_id, str) or not isinstance(query_hash, str):
                raise RetrievalReadBindingError("read-result binding is malformed")
            resolution = self._read_result_cache.resolve_read_result(
                handle, state["run_id"], route_id, query_hash
            )
            if resolution.status not in {"FOUND", "EXHAUSTED"} or resolution.entry is None:
                raise RetrievalReadBindingError(
                    f"invalid retrieval cache dependency: {resolution.status}"
                )
            resolved.append(resolution.entry.read_result)
        return resolved

    @staticmethod
    def _plans_for_cached_results(
        state: ContextRetrievalLocalState,
        *,
        plans: list[CanonicalSourceFetchPlanV1],
        bindings: Mapping[str, object],
        handles: list[str],
    ) -> list[CanonicalSourceFetchPlanV1]:
        prior = cast(
            Mapping[str, CanonicalSourceFetchPlanV1],
            state.get(CONTEXT_CANONICAL_PLANS_KEY, {}),
        )
        by_route = {**prior, **{plan["route_id"]: plan for plan in plans}}
        result = []
        for handle in handles:
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping) or not isinstance(raw.get("route_id"), str):
                raise RetrievalReadBindingError("read-result binding is malformed")
            route_id = cast(str, raw["route_id"])
            plan = by_route.get(route_id)
            if plan is None:
                raise RetrievalReadBindingError("cached read has no canonical source plan")
            result.append(plan)
        return result

    @staticmethod
    def _bounded_acquisition(result: AcquisitionResultV1) -> AcquisitionResultV1:
        return {
            **result,
            "source_summaries": [
                {key: value for key, value in summary.items() if key != "resources"}
                for summary in result["source_summaries"]
            ],
        }

    @staticmethod
    def _remaining_retrieval_budget(
        state: ContextRetrievalLocalState, provider_calls: int
    ) -> dict[str, int]:
        prior = state.get("acquisition_result")
        remaining = (
            DEFAULT_RETRIEVAL_BUDGET.as_remaining()
            if not isinstance(prior, Mapping)
            else dict(cast(Mapping[str, int], prior.get("remaining_budget", {})))
        )
        remaining["pages"] = max(0, remaining.get("pages", 0) - provider_calls)
        return remaining

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
        if not state.get(CONTEXT_READ_RESULT_HANDLES_KEY):
            return "finalize"
        return route_after_assess_sufficiency(
            {
                "sufficiency": sufficiency,
                "query_attempts": state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
            }
        )

    def _build_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        validated_resource_refs = self._validated_resource_refs(state, frozen_routes)
        validated_container_refs = self._validated_container_refs(frozen_routes)
        query_plan = _require_state_value(state.get("query_plan"), "query plan")
        detail_candidate_refs = state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])
        prior_canonical = state.get(CONTEXT_CANONICAL_PLANS_KEY, {})
        if not prior_canonical:
            patch = build_query_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "build_query": {
                                "plan": query_plan,
                                "frozen_routes": frozen_routes,
                                "route_policies": route_policies,
                                "validated_resource_refs": validated_resource_refs,
                                "validated_container_refs": validated_container_refs,
                                "detail_candidate_refs": detail_candidate_refs,
                            }
                        }
                    },
                )
            )
            canonical_plans = cast(list[CanonicalSourceFetchPlanV1], patch["source_fetch_plans"])
            return {
                **state,
                "source_fetch_plans": canonical_plans,
                CONTEXT_CANONICAL_PLANS_KEY: {plan["route_id"]: plan for plan in canonical_plans},
            }
        bindings = cast(Mapping[str, Mapping[str, str]], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        handles = {
            value["route_id"]: handle
            for handle, value in bindings.items()
            if value["route_id"] in prior_canonical
        }
        try:
            patch = build_query_node(
                cast(
                    Any,
                    {
                        "operation_inputs": {
                            "build_query": {
                                "plan": query_plan,
                                "frozen_routes": frozen_routes,
                                "route_policies": route_policies,
                                "prior_plans": prior_canonical,
                                "prior_read_result_handles": handles,
                                "validated_resource_refs": validated_resource_refs,
                                "validated_container_refs": validated_container_refs,
                                "detail_candidate_refs": detail_candidate_refs,
                            }
                        }
                    },
                )
            )
            canonical_plans = cast(list[CanonicalSourceFetchPlanV1], patch["source_fetch_plans"])
        except Exception:
            return {**state, CONTEXT_FOLLOWUP_OPERATION_KEY: "FINALIZE"}
        operations = {plan["operation_kind"] for plan in canonical_plans}
        if operations == {"NEXT_PAGE"}:
            return {
                **state,
                "source_fetch_plans": canonical_plans,
                CONTEXT_CANONICAL_PLANS_KEY: {
                    **prior_canonical,
                    **{plan["route_id"]: plan for plan in canonical_plans},
                },
                CONTEXT_FOLLOWUP_OPERATION_KEY: "NEXT_PAGE",
                CONTEXT_NEXT_PAGE_HANDLES_KEY: {
                    plan["route_id"]: cast(str, plan["prior_read_result_handle"])
                    for plan in canonical_plans
                },
            }
        if operations in ({"SEARCH"}, {"FREEBUSY"}):
            return {
                **state,
                "source_fetch_plans": canonical_plans,
                CONTEXT_CANONICAL_PLANS_KEY: {
                    **prior_canonical,
                    **{plan["route_id"]: plan for plan in canonical_plans},
                },
                CONTEXT_FOLLOWUP_OPERATION_KEY: "SEARCH",
            }
        if operations == {"DETAIL_FETCH"}:
            return {
                **state,
                "source_fetch_plans": canonical_plans,
                CONTEXT_CANONICAL_PLANS_KEY: {
                    **prior_canonical,
                    **{plan["route_id"]: plan for plan in canonical_plans},
                },
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

    def _materialize_confirmation_interrupt(
        self, *, result: SufficiencyResultV2, request_intent: RequestIntentV2
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build one round's ``(user_interrupt, confirmation_interrupt metadata)``.

        Safe to call with ``self._id_factory()``-backed identifiers only from
        an invocation that has not itself called ``interrupt()`` yet: true
        for ``assess_sufficiency`` (round 1, never replays) and for a
        *freshly self-looped* ``finalize`` invocation about to materialize
        round N+1 and return (not yet resumed, so not yet replayed either).
        ``origin_target`` stays ``retrieval.assess_sufficiency`` -- the
        already-allowlisted (``CONFIRMATION_ORIGIN_TARGETS``) value this
        question always had, even though ``interrupt()`` itself now lives in
        ``finalize``; Tool Route's own ``tool_route.finalize`` shows this
        origin_target/interrupt-owning-node split is already an accepted
        convention, not a new one.
        """
        issue = next(
            (item for item in result["issues"] if item["resolution_source"] == "USER"),
            None,
        )
        slot = "required information" if issue is None else issue["slot"]
        reason_code = (
            "RETRIEVAL_NEEDS_CONFIRMATION"
            if issue is None or not issue["reason_codes"]
            else issue["reason_codes"][0]
        )
        question: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "retrieval.assess_sufficiency",
            "question": f"Please clarify the retrieval requirement: {slot}",
            "affected_field_paths": [slot],
            "reason_code": reason_code,
            "known_context_summary": request_intent["goal"],
            "options": [],
        }
        interrupt_id = self._id_factory()
        user_interrupt = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        confirmation_interrupt = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "RETRIEVAL",
            "origin_target": question["origin_target"],
        }
        return user_interrupt, confirmation_interrupt

    def _finalize_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        result = cast(SufficiencyResultV2, state[CONTEXT_SUFFICIENCY_OUTPUT_KEY])

        if result["status"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            state, result = self._resolve_confirmation_inline(state)
            if result is None:
                # RequestConfirmation not applied / ResumeConfirmation
                # conflict -- the confirm_inline callback already built the
                # correct end-of-run state patch. Never loop back from here.
                return cast(
                    ContextRetrievalLocalState,
                    {**state, "__context_retrieval_retry_confirmation__": False},
                )
            if result["status"] == "NEEDS_CONFIRMATION":
                # Still ambiguous after this round's answer. Do NOT call
                # interrupt() again inside this already-resumed task -- see
                # module docstring / Tool Route's established rationale.
                # Materialize the next round's payload (self._id_factory()
                # is safe here: this "finalize" invocation has not itself
                # paused yet) and cleanly return so the self-loop
                # conditional edge re-enters "finalize" as a fresh, separate
                # task for that round.
                request_intent = _require_state_value(state["request_intent"], "request_intent")
                user_interrupt, confirmation_interrupt = self._materialize_confirmation_interrupt(
                    result=result, request_intent=request_intent
                )
                prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
                prompt_context["confirmation_interrupt"] = confirmation_interrupt
                return cast(
                    ContextRetrievalLocalState,
                    {
                        **state,
                        "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                        "user_interrupt": cast(Any, user_interrupt),
                        "prompt_context": prompt_context,
                        "__context_retrieval_retry_confirmation__": True,
                    },
                )

        return self._finalize_resolved(state, result=result)

    def _resolve_confirmation_inline(
        self, state: ContextRetrievalLocalState
    ) -> tuple[ContextRetrievalLocalState, Any]:
        """Pause via a real nested-subgraph ``interrupt()``, then resolve the
        bounded ``ConfirmationResponseProjectionV1`` with exactly one more
        ``retrieval.assess_sufficiency`` call -- not by re-entering
        ``select_evidence`` or re-reading any
        provider data. Returns ``(state, None)`` when the caller must return
        ``state`` immediately (not-applied/conflict end state); otherwise
        ``(updated_state, resolved_result)``.

        This whole method's body replays from the top on resume (LangGraph's
        standard node-replay semantics for the node containing
        ``interrupt()``) -- every value it depends on before the interrupt
        call is either read unchanged from state (set once by
        ``assess_sufficiency``, a node that itself never replays) or is
        itself the idempotency-guarded, side-effect-free core in
        ``confirm_inline``.
        """
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(ContextRetrievalLocalState, {**state, **early_return_patch}), None
        assert confirmation_response is not None

        sufficiency_result, llm_provider_result, retry_budget = self._run_sufficiency_attempt(
            state, confirmation_response=confirmation_response
        )

        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)

        updated_state = cast(
            ContextRetrievalLocalState,
            {
                **state,
                CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
                "llm_provider_result": llm_provider_result,
                "retry_budget": retry_budget,
                "user_interrupt": None,
                "prompt_context": prompt_context,
            },
        )
        return updated_state, sufficiency_result

    def _finalize_resolved(
        self, state: ContextRetrievalLocalState, *, result: SufficiencyResultV2
    ) -> ContextRetrievalLocalState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        sufficiency = state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]
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
            patch = finalize_retrieval_node(
                cast(
                    RetrievalStateV2,
                    {
                        "request_intent": _require_state_value(
                            state["request_intent"], "request_intent"
                        ),
                        "evidence_selection": selection,
                        "sufficiency": sufficiency,
                        "availability_results": state.get("availability_results", []),
                        "exclusion_obligation_segment_ids": state.get(
                            "exclusion_obligation_segment_ids", []
                        ),
                    },
                ),
                artifact_id=self._id_factory(),
                tool_route_plan=_require_state_value(state["tool_route_plan"], "tool_route_plan"),
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
                evidence_drafts=state["evidence_drafts"],
                current_round_no=state[CONTEXT_CURRENT_ROUND_NO_KEY],
                prior_result=state.get("retrieval_result"),
            )
            retrieval_result = cast(Any, patch["final_result"])
        self._evidence_store.put(run_id=state["run_id"], evidence_drafts=state["evidence_drafts"])
        retrieval_return: RetrievalRouteResultV1 = {
            "disposition": cast(str, result["status"]),
            "typed_result": retrieval_result,
        }
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=retrieval_return,
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
                "__context_retrieval_retry_confirmation__": False,
            },
            {"workflow_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value},
            decision,
        )
        if retrieval_result is not None:
            merged["retrieval_result"] = retrieval_result
            merged["pending_user_retrieval_need"] = None
            merged["exclusion_obligation_segment_ids"] = []
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
        merged.pop(CONTEXT_READ_BINDINGS_KEY, None)
        merged.pop("query_plan", None)
        merged.pop("query_attempts", None)
        merged.pop("source_statuses", None)
        merged.pop("read_result_handles", None)
        merged.pop("segment_handles", None)
        merged.pop("rag_candidates", None)
        merged.pop("evidence_selection", None)
        merged.pop("sufficiency", None)
        merged.pop("final_result", None)
        merged.pop("input_route_ref", None)
        merged.pop("input_routes", None)
        merged.pop("segments", None)
        merged.pop("ranked_segments", None)
        merged.pop("availability_results", None)
        merged.pop("evidence_drafts", None)
        merged.pop("llm_provider_result", None)
        merged.pop("source_fetch_plans", None)
        merged.pop("acquisition_result", None)
        return cast(ContextRetrievalLocalState, merged)

    def _bounded_read_result_summaries(
        self, state: ContextRetrievalLocalState
    ) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        bindings = cast(Mapping[str, object], state.get(CONTEXT_READ_BINDINGS_KEY, {}))
        for handle in cast(list[str], state.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])):
            raw = bindings.get(handle)
            if not isinstance(raw, Mapping):
                continue
            route_id = raw.get("route_id")
            query_hash = raw.get("query_identity_hash")
            if not isinstance(route_id, str) or not isinstance(query_hash, str):
                continue
            resolution = self._read_result_cache.resolve_read_result(
                handle, state["run_id"], route_id, query_hash
            )
            if resolution.entry is None:
                continue
            token = resolution.entry.read_result.next_page_token
            output = resolution.entry.read_result.output
            raw_items = output.get("items", [])
            count = len(raw_items) if isinstance(raw_items, list) else 1 if "item" in output else 0
            summaries.append(
                {
                    "read_result_handle": handle,
                    "route_id": route_id,
                    "query_identity_hash": query_hash,
                    "has_next_page": token is not None,
                    "exhausted": resolution.status == "EXHAUSTED",
                    "result_count": count,
                    "page_state_hash": None
                    if token is None
                    else sha256(token.encode()).hexdigest(),
                }
            )
        return summaries


def _retrieval_required_signal(signal: object) -> RetrievalRequiredV1 | None:
    if isinstance(signal, dict) and signal.get("kind") == "RETRIEVAL_REQUIRED":
        return cast(RetrievalRequiredV1, signal)
    return None


def _pending_retrieval_need(value: object) -> RetrievalNeedV1 | None:
    if not isinstance(value, Mapping):
        return None
    required_information = value.get("required_information")
    reason_codes = value.get("reason_codes")
    if not isinstance(required_information, str) or not required_information:
        raise ValueError("pending Retrieval need requires bounded required_information")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) and item for item in reason_codes
    ):
        raise ValueError("pending Retrieval need requires reason_codes")
    return {
        "required_information": required_information,
        "reason_codes": list(reason_codes),
    }


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
