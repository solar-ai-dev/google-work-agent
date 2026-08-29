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
        'return "rag_retrieve"'
        in (owner / "routing/route_after_normalize_segments.py").read_text()
    )


def test_production_retrieval_uses_exact_five_core_node_boundaries() -> None:
    root = Path(__file__).resolve().parents[5]
    source = (
        root
        / "src/google_work_agent/adapters/langgraph/subgraphs/projected_context_retrieval.py"
    ).read_text()
    for node_name in (
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve",
    ):
        assert f'graph.add_node("{node_name}"' in source
    for legacy_name in (
        "execute_initial_read",
        "plan_followup",
        "execute_next_page",
        "execute_followup_search",
        "execute_detail",
    ):
        assert f'graph.add_node("{legacy_name}"' not in source

    operation_source = (
        root / "src/google_work_agent/adapters/langgraph/subgraphs/context_retrieval.py"
    ).read_text()
    assert "resolve_availability(" in operation_source
    assert 'graph.add_node("resolve_availability"' not in source
