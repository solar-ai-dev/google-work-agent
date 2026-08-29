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
        graph.add_node("plan_query", self._plan_query_node)
        graph.add_node("build_query", self._build_query_node)
        graph.add_node("execute_read", self._execute_read_node)
        graph.add_node("normalize_segments", self._normalize_segments_node)
        graph.add_node("rag_retrieve", self._rag_retrieve_node)
        graph.add_node("select_evidence", self._select_evidence_node)
        graph.add_node("selection_validate", self._selection_validate_node)
        graph.add_node("assess_sufficiency", self._assess_sufficiency_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_conditional_edges(
            "init",
            self._route_after_init,
            {"plan_query": "plan_query", "normalize_segments": "normalize_segments"},
        )
        graph.add_edge("plan_query", "build_query")
        graph.add_conditional_edges(
            "build_query",
            self._route_after_build_query,
            {"execute_read": "execute_read", "finalize": "finalize"},
        )
        graph.add_edge("execute_read", "normalize_segments")
        graph.add_edge("normalize_segments", "rag_retrieve")
        graph.add_edge("rag_retrieve", "select_evidence")
        graph.add_edge("select_evidence", "selection_validate")
        graph.add_edge("selection_validate", "assess_sufficiency")
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
        return graph.compile(name="context_retriever_subgraph")

    def _normalize_segments_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        safe_acquisition = (
            None
            if acquisition is None
            else sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        )
        result = super()._normalize_segments_node(self._ephemeral_raw_state(state))
        return cast(
            ContextRetrievalLocalState,
            {**result, "acquisition_result": safe_acquisition},
        )

    def _rag_retrieve_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        return self._with_ephemeral_acquisition(state, super()._rag_retrieve_node)

    def _select_evidence_node(
        self, state: ContextRetrievalLocalState
    ) -> ContextRetrievalLocalState:
        return self._with_ephemeral_acquisition(state, super()._select_evidence_node)

    def _with_ephemeral_acquisition(
        self,
        state: ContextRetrievalLocalState,
        operation: Any,
    ) -> ContextRetrievalLocalState:
        acquisition = state.get("acquisition_result")
        safe_acquisition = (
            None
            if acquisition is None
            else sanitize_acquisition_result(cast(AcquisitionResultV1, acquisition))
        )
        result = operation(self._ephemeral_raw_state(state))
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

    def _build_context_result(self, state: ContextRetrievalLocalState) -> ContextRetrievalResultV1:
        return super()._build_context_result(self._ephemeral_raw_state(state))

    def _ephemeral_raw_state(self, state: ContextRetrievalLocalState) -> ContextRetrievalLocalState:
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
            # topology authority, so every node consumes the same bounded
            # projection. Mixing the first node's raw payload with later
            # checkpoint-safe projections would make SourceSegmentIdentityV1
            # unstable for one resource within a single retrieval run.
            hydrated = safe
        return cast(ContextRetrievalLocalState, {**state, "acquisition_result": hydrated})


__all__ = ["ProjectedContextRetrieverSubgraph"]
