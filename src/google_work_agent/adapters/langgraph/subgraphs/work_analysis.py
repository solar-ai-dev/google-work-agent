"""Work-analysis native LangGraph subgraph.

init -> analyze -> result_validate -> finalize
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
    ANALYSIS_AGENT_LOCAL_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import WorkAnalysisLocalState
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    SupervisorDecisionV1,
    WorkAnalysisAgent,
    WorkflowPhase,
    route_supervisor,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]


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
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            WorkAnalysisLocalState,
            input_schema=GraphState,
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
        graph.add_edge("finalize", END)
        return graph.compile(name="work_analysis_subgraph")

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
                "context_result": _require_state_value(state["context_result"], "context_result"),
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

    def _analyze_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        llm_result = self._agent.invoke_analyze_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            context_result=_require_state_value(state["context_result"], "context_result"),
            request=request,
        )
        result = self._agent.build_output_from_llm_result(
            llm_result,
            context_result=_require_state_value(state["context_result"], "context_result"),
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "ANALYZE_COMPLETE"
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
                node_name="analyze",
                llm_call_id=f"{request.run_id}:analysis.analyze",
                prompt_ref=self._agent.analyze_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

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
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        result = _require_state_value(state["analysis_result"], "analysis_result")
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
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return cast(WorkAnalysisLocalState, merged)
