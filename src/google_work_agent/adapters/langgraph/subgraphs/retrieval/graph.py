"""Canonical Retrieval LangGraph subgraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes.assess_sufficiency_node import (
    assess_sufficiency_node,
)
from .nodes.build_query_node import (
    build_query_node,
)
from .nodes.execute_read_node import (
    execute_read_node,
)
from .nodes.finalize_retrieval_node import (
    finalize_retrieval_node,
)
from .nodes.normalize_segments_node import (
    normalize_segments_node,
)
from .nodes.plan_query_node import (
    plan_query_node,
)
from .nodes.rag_retrieve_rerank_node import (
    rag_retrieve_rerank_node,
)
from .nodes.select_evidence_node import (
    select_evidence_node,
)
from .routing.route_after_assess_sufficiency import (
    route_after_assess_sufficiency,
)
from .routing.route_after_build_query import (
    route_after_build_query,
)
from .routing.route_after_execute_read import (
    route_after_execute_read,
)
from .routing.route_after_normalize_segments import (
    route_after_normalize_segments,
)
from .routing.route_after_plan_query import (
    route_after_plan_query,
)
from .routing.route_after_rag_retrieve_rerank import (
    route_after_rag_retrieve_rerank,
)
from .state import RetrievalState


def build_retrieval_graph() -> Any:
    graph = StateGraph(RetrievalState)
    graph.add_node("plan_query", plan_query_node)
    graph.add_node("build_query", build_query_node)
    graph.add_node("execute_read", execute_read_node)
    graph.add_node("normalize_segments", normalize_segments_node)
    graph.add_node("rag_retrieve", rag_retrieve_rerank_node)
    graph.add_node("select_evidence", select_evidence_node)  # type: ignore[type-var]
    graph.add_node("assess_sufficiency", assess_sufficiency_node)  # type: ignore[type-var]
    graph.add_node("finalize_retrieval", finalize_retrieval_node)  # type: ignore[type-var]
    graph.add_edge(START, "plan_query")
    graph.add_conditional_edges(
        "plan_query", route_after_plan_query, {"build_query": "build_query"}
    )
    graph.add_conditional_edges(
        "build_query", route_after_build_query, {"execute_read": "execute_read"}
    )
    graph.add_conditional_edges(
        "execute_read", route_after_execute_read, {"normalize_segments": "normalize_segments"}
    )
    graph.add_conditional_edges(
        "normalize_segments",
        route_after_normalize_segments,
        {"rag_retrieve": "rag_retrieve"},
    )
    graph.add_conditional_edges(
        "rag_retrieve",
        route_after_rag_retrieve_rerank,
        {"select_evidence": "select_evidence"},
    )
    graph.add_edge("select_evidence", "assess_sufficiency")
    graph.add_conditional_edges(
        "assess_sufficiency",
        route_after_assess_sufficiency,
        {"plan_query": "plan_query", "finalize_retrieval": "finalize_retrieval"},
    )
    graph.add_edge("finalize_retrieval", END)
    return graph.compile()
