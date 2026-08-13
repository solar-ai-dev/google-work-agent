"""Request-understanding native LangGraph subgraph (init -> classify -> finalize)."""

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
    REQUEST_AGENT_LOCAL_KEY,
    REQUEST_OUTPUT_KEY,
    GraphState,
    ParentGraphState,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    RequestUnderstandingLocalState,
)
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RequestUnderstandingAgent,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]


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
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            RequestUnderstandingLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("classify", self._classify_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "classify")
        graph.add_edge("classify", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="request_understanding_subgraph")

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
        llm_result = self._agent.invoke_classify_llm(request)
        output = self._agent.build_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "CLASSIFY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            REQUEST_OUTPUT_KEY: output,
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

    def _finalize_node(
        self, state: RequestUnderstandingLocalState
    ) -> RequestUnderstandingLocalState:
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        request = request_from_state(state)
        output = state[REQUEST_OUTPUT_KEY]
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
            },
            self._agent.build_state_update(output, request=request),
            decision,
        )
        merged.pop(REQUEST_AGENT_LOCAL_KEY, None)
        merged.pop(REQUEST_OUTPUT_KEY, None)
        return cast(RequestUnderstandingLocalState, merged)
