"""Canonical Retrieval LangGraph subgraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.finalize_retrieval_node import (
    finalize_retrieval_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.select_evidence_node import (
    select_evidence_node,
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
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    rag_retrieve_rerank,
)
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
    allowed_read_tool_ids,
)
from google_work_agent.application.orchestration.api_acquisition import retrieval_query_hash
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
from google_work_agent.application.orchestration.retrieval_data_boundary import (
    hydrate_acquisition_for_segmentation,
    sanitize_acquisition_result,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.orchestration.retrieval_planner_input import (
    followup_retrieval_planner_input,
    initial_retrieval_planner_input,
)
from google_work_agent.application.orchestration.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.orchestration.retrieval_read_cache import (
    ReadResultContinuationError,
    RunScopedReadResultCache,
)
from google_work_agent.application.orchestration.retrieval_read_executor import (
    RetrievalReadExecutor,
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
from google_work_agent.application.orchestration.source_fetch_plan_builder import (
    RouteConstraintPolicy,
    SourceFetchPlanBuilder,
)
from google_work_agent.application.orchestration.source_fetch_plan_execution_projection import (
    project_for_legacy_read_executor,
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
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

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
    timezones = {
        str(constraint["timezone"])
        for plan in canonical_plans.values()
        if plan["resource_type"].startswith("CALENDAR")
        for constraint in plan["effective_constraints"]
        if constraint["kind"] == "TEMPORAL_RANGE"
    }
    freebusy_resources = [
        resource
        for summary in acquisition_result["source_summaries"]
        for resource in cast(list[dict[str, object]], summary.get("resources", []))
        if resource.get("resource_type") == "calendar_freebusy"
    ]
    if not freebusy_resources:
        return []
    if len(timezones) != 1:
        raise ValueError("FreeBusy availability requires one frozen calendar timezone")
    timezone = next(iter(timezones))
    results: list[AvailableIntervalV1] = []
    for resource in freebusy_resources:
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
        acquisition_agent: Any,
        retrieval_query_planner: RetrievalQueryPlannerAgent,
        source_fetch_plan_builder: SourceFetchPlanBuilder,
        read_result_cache: RunScopedReadResultCache,
        retrieval_read_executor: RetrievalReadExecutor,
        confirm_inline: ConfirmInline,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._select_prompt_ref = load_prompt_reference("retrieval.select_evidence", manifest_path)
        self._sufficiency_prompt_ref = load_prompt_reference(
            "retrieval.assess_sufficiency", manifest_path
        )
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
        segments = cast(list[Any], normalize_segments(acquisition_result=acquisition_result))
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
        segments = cast(list[Any], normalize_segments(acquisition_result=acquisition_result))
        expected_ids = state.get("segments")
        actual_ids = [segment.segment_id for segment in segments]
        if expected_ids is not None and actual_ids != expected_ids:
            raise ValueError("stable segment identity changed within one retrieval round")
        return segments

    def _ephemeral_raw_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        if acquisition is None:
            return state
        safe = sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        if state.get(CONTEXT_READ_RESULT_HANDLES_KEY):
            hydrated = hydrate_acquisition_for_segmentation(
                run_id=state["run_id"],
                result=safe,
                read_result_cache=self._read_result_cache,
            )
        else:
            hydrated = safe
        return cast(
            ContextRetrievalLocalState,
            {**state, "acquisition_result": hydrated},
        )

    def _rag_retrieve_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        segments = self._normalized_segments(state)
        candidates = rag_retrieve_rerank(
            cast(list[Any], segments),
            request_intent=request_intent,
            top_k=24,
        )
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

    def _validated_task_container_refs(
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

    def _plan_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        if CONTEXT_AGENT_LOCAL_KEY not in state:
            state = self._initialize_state(state)
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
        ensure_llm_call_budget(state)
        query_plan, revised_retry_budget = self._retrieval_query_planner.plan(
            prompt_input=prompt_input,
            trace_context=_retrieval_trace_context(state, "retrieval.plan_query"),
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            retry_budget=cast(RunBudgetV2, state["retry_budget"]),
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=state.get(CONTEXT_SEGMENT_HANDLES_KEY, []),
        )
        return {
            **state,
            "query_plan": query_plan,
            "retry_budget": consume_llm_call_budget(
                {**state, "retry_budget": revised_retry_budget}, provider_calls_consumed=1
            ),
        }

    def _execute_read_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        operation = state.get(CONTEXT_FOLLOWUP_OPERATION_KEY)
        if operation == "NEXT_PAGE":
            result = self._execute_next_page_node(state)
        elif operation == "DETAIL_FETCH":
            result = self._execute_detail_node(state)
        elif state.get("acquisition_result") is not None:
            result = self._execute_followup_search_node(state)
        else:
            result = self._execute_initial_read_node(state)
        return cast(
            ContextRetrievalLocalState,
            {
                **result,
                "read_result_handles": list(result.get(CONTEXT_READ_RESULT_HANDLES_KEY, [])),
                "segment_handles": list(result.get(CONTEXT_SEGMENT_HANDLES_KEY, [])),
                "query_attempts": list(result.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])),
            },
        )

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
                return route_after_assess_sufficiency(
                    {
                        "sufficiency": sufficiency,
                        "query_attempts": state.get(CONTEXT_QUERY_ATTEMPTS_KEY, []),
                    }
                )
        return "finalize"

    def _build_query_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        tool_route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
        frozen_routes = tool_route_plan["input_plan"]["input_routes"]
        route_policies = _runtime_route_constraint_policies(frozen_routes)
        validated_container_refs = self._validated_task_container_refs(frozen_routes)
        query_plan = _require_state_value(state.get("query_plan"), "query plan")
        detail_candidate_refs = state.get(CONTEXT_SEGMENT_HANDLES_KEY, [])
        prior_canonical = state.get(CONTEXT_CANONICAL_PLANS_KEY, {})
        prior_legacy = cast(list[Any], state.get("source_fetch_plans", []))
        if not prior_canonical:
            canonical_plans = self._source_fetch_plan_builder.build(
                query_plan,
                frozen_routes=frozen_routes,
                route_policies=route_policies,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            )
            return {
                **state,
                "source_fetch_plans": project_for_legacy_read_executor(
                    canonical_plans,
                    frozen_routes=frozen_routes,
                    retrieval_budget=self._acquisition_agent.retrieval_budget,
                ),
                CONTEXT_CANONICAL_PLANS_KEY: {plan["route_id"]: plan for plan in canonical_plans},
            }
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

    def _append_read_attempts(
        self,
        *,
        state: ContextRetrievalLocalState,
        result: Any,
        plans: list[Any],
        operation_kind: str,
        previous_query_hash: str | None,
    ) -> list[QueryAttemptV1]:
        attempts = cast(list[QueryAttemptV1], list(state.get(CONTEXT_QUERY_ATTEMPTS_KEY, [])))
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
