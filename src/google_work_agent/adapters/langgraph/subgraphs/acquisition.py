"""Acquisition native LangGraph subgraph.

init -> plan_sources -> plan_validate -[PLAN_READY]-> deterministic_read
                                                            -> result_validate -> finalize
                                       -[else]------------------------------------^
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.graph_state import (
    ACQUISITION_AGENT_LOCAL_KEY,
    ACQUISITION_PLANNING_OUTPUT_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import AcquisitionLocalState
from google_work_agent.application.workflows import (
    AdditionalAcquisitionRequestV1,
    AgentLocalStateV1,
    ApiDiscoveryAcquisitionAgent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
    validate_acquisition_result_v1,
)
from google_work_agent.application.workflows.retrieval_read_cache import RunScopedReadResultCache

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]


class AcquisitionSubgraph:
    """Builds and executes the ``acquisition`` native subgraph."""

    def __init__(
        self,
        *,
        agent: ApiDiscoveryAcquisitionAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        read_result_cache: RunScopedReadResultCache,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._read_result_cache = read_result_cache

    def build(self) -> Any:
        graph = StateGraph(
            AcquisitionLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("plan_sources", self._plan_sources_node)
        graph.add_node("plan_validate", self._plan_validate_node)
        graph.add_node("deterministic_read", self._read_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "plan_sources")
        graph.add_edge("plan_sources", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="acquisition_subgraph")

    def _init_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        additional: AdditionalAcquisitionRequestV1 | None = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if context_result is not None:
            additional = context_result["additional_acquisition_request"]
        if additional is None and analysis_result is not None:
            additional = analysis_result["additional_acquisition_request"]
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="api_discovery_acquisition",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "additional_acquisition_request": additional,
                "entry_mode": request.entry_mode,
            },
            prompt_ref=self._agent.prompt_ref,
        )
        next_state: AcquisitionLocalState = {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=invocation_id,
                subgraph_namespace="acquisition",
                node_name="init",
                prompt_ref=self._agent.prompt_ref,
                agent_invocation_increment=1,
            ),
        }
        return next_state

    def _plan_sources_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        additional: AdditionalAcquisitionRequestV1 | None = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if context_result is not None:
            additional = context_result["additional_acquisition_request"]
        if additional is None and analysis_result is not None:
            additional = analysis_result["additional_acquisition_request"]
        llm_result = self._agent.invoke_plan_sources_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            request=request,
            additional_acquisition_request=additional,
            tool_route_plan=state.get("tool_route_plan"),
        )
        output = self._agent.build_planning_output_from_llm_result(
            llm_result,
            tool_route_plan=state.get("tool_route_plan"),
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            ACQUISITION_PLANNING_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_sources",
                llm_call_id=f"{request.run_id}:acquisition.plan_sources",
                prompt_ref=self._agent.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }

    def _plan_validate_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        source_fetch_plans = planning_output.get("source_fetch_plans")
        if not isinstance(source_fetch_plans, list):
            raise TypeError("acquisition planning output is missing source_fetch_plans")
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = planning_output
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_validate",
            ),
        }

    def _route_plan_validate(self, state: AcquisitionLocalState) -> str:
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        return "deterministic_read" if planning_output["result"] == "PLAN_READY" else "finalize"

    def _read_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        result = self._agent.acquire(
            plans=planning_output["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
            tool_route_plan=state.get("tool_route_plan"),
            read_result_cache=self._read_result_cache,
            read_handle_factory=self._id_factory,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="deterministic_read",
            ),
        }

    def _result_validate_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        acquisition_result = validate_acquisition_result_v1(state["acquisition_result"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], acquisition_result)
        return {
            **state,
            "acquisition_result": acquisition_result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: AcquisitionLocalState) -> AcquisitionLocalState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        current: AcquisitionLocalState = {
            **state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="finalize",
            ),
        }
        if planning_output["result"] != "PLAN_READY":
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=planning_output,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, planning_output["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                self._agent.build_planning_state_update(planning_output),
                decision,
            )
        else:
            acquisition_result = _require_state_value(
                state["acquisition_result"], "acquisition_result"
            )
            decision = route_supervisor(
                phase=WorkflowPhase.API_ACQUISITION,
                state=cast(MultiAgentGraphState, current),
                result=acquisition_result,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, acquisition_result["status"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    **self._agent.build_planning_state_update(planning_output),
                    **self._agent.build_acquisition_state_update(acquisition_result),
                },
                decision,
            )
        merged.pop(ACQUISITION_AGENT_LOCAL_KEY, None)
        merged.pop(ACQUISITION_PLANNING_OUTPUT_KEY, None)
        return cast(AcquisitionLocalState, merged)
