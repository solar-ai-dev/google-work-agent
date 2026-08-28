"""Canonical Retrieval LangGraph subgraph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

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
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.rag_retrieve_rerank_node import (
    rag_retrieve_rerank_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.select_evidence_node import (
    select_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_assess_sufficiency import (
    route_after_assess_sufficiency,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.state import RetrievalState


def build_retrieval_graph():
    graph = StateGraph(RetrievalState)
    graph.add_node("plan_query", plan_query_node)
    graph.add_node("build_query", build_query_node)
    graph.add_node("execute_read", execute_read_node)
    graph.add_node("normalize_segments", normalize_segments_node)
    graph.add_node("rag_retrieve_rerank", rag_retrieve_rerank_node)
    graph.add_node("select_evidence", select_evidence_node)
    graph.add_node("assess_sufficiency", assess_sufficiency_node)
    graph.add_node("finalize_retrieval", finalize_retrieval_node)
    graph.add_edge(START, "plan_query")
    graph.add_edge("plan_query", "build_query")
    graph.add_edge("build_query", "execute_read")
    graph.add_edge("execute_read", "normalize_segments")
    graph.add_edge("normalize_segments", "rag_retrieve_rerank")
    graph.add_edge("rag_retrieve_rerank", "select_evidence")
    graph.add_edge("select_evidence", "assess_sufficiency")
    graph.add_conditional_edges(
        "assess_sufficiency",
        route_after_assess_sufficiency,
        {"plan_query": "plan_query", "finalize_retrieval": "finalize_retrieval"},
    )
    graph.add_edge("finalize_retrieval", END)
    return graph.compile()
