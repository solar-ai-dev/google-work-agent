from pathlib import Path


def test_resolve_entity__relations_exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    assert (
        "project_resolve_entity_relations_input"
        in (owner / "nodes/resolve_entity_relations_node.py").read_text()
    )
    assert (owner / "projections/resolve_entity_relations_projection.py").exists()
    assert (
        'return "resolve_temporal_dependencies"'
        in (owner / "routing/route_after_resolve_entity_relations.py").read_text()
    )
