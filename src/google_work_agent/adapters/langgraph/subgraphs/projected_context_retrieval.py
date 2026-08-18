"""Typed parent-input boundary for the Retrieval V2 native subgraph.

The Retrieval implementation remains in ``context_retrieval.py``. This class
only replaces the LangGraph parent input schema so the subgraph receives its
role-scoped projection instead of the entire Main Graph state.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.graph_state import ParentGraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    ContextRetrievalInputState,
    ContextRetrievalLocalState,
)

from .context_retrieval import ContextRetrieverSubgraph


class ProjectedContextRetrieverSubgraph(ContextRetrieverSubgraph):
    """ContextRetrieverSubgraph with a narrowed typed parent projection."""

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
        graph.add_edge("finalize", END)
        return graph.compile(name="context_retriever_subgraph")


__all__ = ["ProjectedContextRetrieverSubgraph"]
