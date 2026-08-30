import re
from pathlib import Path


def test_normalize_segments_exact_node_projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert (
        "project_normalize_segments_input"
        in (owner / "nodes/normalize_segments_node.py").read_text()
    )
    assert (owner / "projections/normalize_segments_projection.py").exists()
    assert (
        'return "rag_retrieve"' in (owner / "routing/route_after_normalize_segments.py").read_text()
    )


def test_production_retrieval_uses_exact_eight_node_boundaries() -> None:
    root = Path(__file__).resolve().parents[5]
    source = (
        root / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py"
    ).read_text()
    expected = {
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve",
        "select_evidence",
        "assess_sufficiency",
        "finalize",
    }
    assert set(re.findall(r'graph\.add_node\("([^"]+)"', source)) == expected
    for legacy_name in (
        "execute_initial_read",
        "plan_followup",
        "execute_next_page",
        "execute_followup_search",
        "execute_detail",
    ):
        assert f'graph.add_node("{legacy_name}"' not in source

    assert "resolve_availability(" in source
    assert 'graph.add_node("resolve_availability"' not in source

    for node_symbol in (
        "plan_query_node",
        "build_query_node",
        "execute_read_node",
        "normalize_segments_node",
        "rag_retrieve_rerank_node",
        "select_evidence_node",
        "assess_sufficiency_node",
        "finalize_retrieval_node",
    ):
        assert f"nodes.{node_symbol.removesuffix('_node')}_node import" in source
        assert f"{node_symbol}(" in source

    for router_symbol in (
        "route_after_plan_query",
        "route_after_build_query",
        "route_after_execute_read",
        "route_after_normalize_segments",
        "route_after_rag_retrieve_rerank",
        "route_after_select_evidence",
        "route_after_assess_sufficiency",
        "route_after_finalize_retrieval",
    ):
        assert f"{router_symbol}," in source
        assert f"{router_symbol}(" in source or f"            {router_symbol}," in source

    for operation in (
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve_rerank",
    ):
        assert re.search(rf"(?<![\w]){operation}\(", source) is None

    composition = (
        root / "src/google_work_agent/adapters/langgraph/pre_analysis_composition.py"
    ).read_text()
    assert "subgraphs.retrieval.graph" in composition
    assert "ProjectedContextRetrieverSubgraph" not in composition
    assert "ContextRetrieverSubgraph" not in composition
