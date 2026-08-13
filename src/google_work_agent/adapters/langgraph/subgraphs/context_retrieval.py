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
    CONTEXT_SELECTION_OUTPUT_KEY,
    CONTEXT_SUFFICIENCY_OUTPUT_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import ContextRetrievalLocalState
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    ContextRetrievalAgent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    SupervisorDecisionV1,
    WorkflowPhase,
    route_supervisor,
    validate_context_retrieval_result_v1,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]


class ContextRetrieverSubgraph:
    """Builds and executes the ``context_retriever`` native subgraph."""

    def __init__(
        self,
        *,
        agent: ContextRetrievalAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            ContextRetrievalLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("select_evidence", self._select_evidence_node)
        graph.add_node("selection_validate", self._selection_validate_node)
        graph.add_node("assess_sufficiency", self._assess_sufficiency_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "select_evidence")
        graph.add_edge("select_evidence", "selection_validate")
        graph.add_edge("selection_validate", "assess_sufficiency")
        graph.add_edge("assess_sufficiency", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="context_retriever_subgraph")

    def _init_node(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="context_retriever",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "acquisition_result": _require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
            },
            prompt_ref=self._agent.select_prompt_ref,
        )
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: local_state,
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

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        acquisition_result = _require_state_value(state["acquisition_result"], "acquisition_result")
        segments = self._agent.build_segments_from_acquisition(acquisition_result)
        selection = self._agent.select_evidence(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            acquisition_result=acquisition_result,
            request=request,
            segments=cast(list[Any], segments),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECT_EVIDENCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
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
            missing_information=selection["missing_information"],
            ambiguity=selection["ambiguity"],
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
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            request=request,
            context_bundle=state["context_bundle"],
            evidence_drafts=state["evidence_drafts"],
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SUFFICIENCY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], sufficiency_result)
        return {
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
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=result,
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
        merged.pop(CONTEXT_SELECTION_OUTPUT_KEY, None)
        merged.pop(CONTEXT_SUFFICIENCY_OUTPUT_KEY, None)
        merged.pop("evidence_drafts", None)
        merged.pop("llm_provider_result", None)
        return cast(ContextRetrievalLocalState, merged)
