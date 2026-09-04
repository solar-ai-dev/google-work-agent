from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_resolve_entity_relations as route_module,
)


def test_entity_relations__without_temporal_fact__continue_to_duplicate_analysis() -> None:
    assert route_module.route_after_resolve_entity_relations(
        {
            "fact_candidates": [
                {"fact_id": "fact-1", "kind": "TASK"},
                {"fact_id": "fact-2", "kind": "PERSON"},
            ]
        }
    ) == "detect_duplicate_conflict_candidates"


def test_entity_relations__with_temporal_fact__continue_to_temporal_analysis() -> None:
    assert route_module.route_after_resolve_entity_relations(
        {
            "fact_candidates": [
                {"fact_id": "fact-1", "kind": "PERSON"},
                {"fact_id": "fact-2", "kind": "DEADLINE"},
            ]
        }
    ) == "resolve_temporal_dependencies"
