from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_extract_work_facts as route_module,
)


def test_empty_fact_set_skips_relation_provider_calls() -> None:
    assert route_module.route_after_extract_work_facts(
        {"fact_candidates": []}
    ) == "validate_relations"


def test_nonempty_fact_set_keeps_relation_analysis() -> None:
    assert (
        route_module.route_after_extract_work_facts(
            {"fact_candidates": [{"fact_id": "fact-1"}]}
        )
        == "resolve_entity_relations"
    )
