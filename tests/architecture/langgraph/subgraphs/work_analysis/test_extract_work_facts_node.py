from pathlib import Path


def test_extract_work__facts_exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    assert (
        "project_extract_work_facts_input"
        in (owner / "nodes/extract_work_facts_node.py").read_text()
    )
    assert (owner / "projections/extract_work_facts_projection.py").exists()
    router = (owner / "routing/route_after_extract_work_facts.py").read_text()
    assert 'return "validate_relations"' in router
    assert 'return "resolve_entity_relations"' in router
