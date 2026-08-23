"""Typed parent-input boundary for the Retrieval V2 native subgraph.

The Retrieval implementation remains in ``context_retrieval.py``. This class
narrows the parent input schema and enforces the raw-source checkpoint boundary:
provider payload is resolved from the run cache only for synchronous
segmentation/materialization calls and is restored to bounded state before a
LangGraph node returns.
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.main.state import (
    CONTEXT_READ_RESULT_HANDLES_KEY,
    ParentGraphState,
)
from google_work_agent.adapters.langgraph.subgraph_state import (
    ContextRetrievalInputState,
    ContextRetrievalLocalState,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ContextRetrievalResultV1,
)
from google_work_agent.application.orchestration.retrieval_data_boundary import (
    hydrate_acquisition_for_segmentation,
    sanitize_acquisition_result,
)

from .context_retrieval import ContextRetrieverSubgraph


class ProjectedContextRetrieverSubgraph(ContextRetrieverSubgraph):
    """ContextRetrieverSubgraph with typed projection and ephemeral raw reads."""

    def build(self) -> Any:
        graph = StateGraph(
            ContextRetrievalLocalState,
            input_schema=ContextRetrievalInputState,
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
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="context_retriever_subgraph")

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        safe_acquisition = (
            None
            if acquisition is None
            else sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        )
        result = super()._select_evidence_node(self._ephemeral_raw_state(state))
        return cast(
            ContextRetrievalLocalState,
            {**result, "acquisition_result": safe_acquisition},
        )

    def _selection_validate_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        safe_acquisition = (
            None
            if acquisition is None
            else sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        )
        result = super()._selection_validate_node(self._ephemeral_raw_state(state))
        return cast(
            ContextRetrievalLocalState,
            {**result, "acquisition_result": safe_acquisition},
        )

    def _build_context_result(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalResultV1:
        return super()._build_context_result(self._ephemeral_raw_state(state))

    def _ephemeral_raw_state(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        if acquisition is None:
            return state
        safe = sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        if state.get(CONTEXT_READ_RESULT_HANDLES_KEY):
            # Native production Retrieval publishes read-result handles before
            # entering segmentation. Missing cache content is therefore a
            # boundary violation and resolve must fail closed.
            hydrated = hydrate_acquisition_for_segmentation(
                run_id=state["run_id"],
                result=safe,
                read_result_cache=self._read_result_cache,
            )
        else:
            # Compatibility-only standalone AcquisitionSubgraph direct calls
            # have no canonical read-result handle. They are not a production
            # topology authority; consume their legacy result transiently and
            # sanitize it before this node returns.
            hydrated = cast(AcquisitionResultV1, acquisition)
        return cast(ContextRetrievalLocalState, {**state, "acquisition_result": hydrated})


__all__ = ["ProjectedContextRetrieverSubgraph"]
