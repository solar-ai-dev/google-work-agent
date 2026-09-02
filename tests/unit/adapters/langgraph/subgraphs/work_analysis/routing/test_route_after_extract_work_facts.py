from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_extract_work_facts as route_module,
)


def test_empty_fact__set_skips__relation_provider_calls() -> None:
    assert route_module.route_after_extract_work_facts(
        {"fact_candidates": []}
    ) == "validate_relations"


def test_nonempty_fact__set_keeps__relation_analysis() -> None:
    assert (
        route_module.route_after_extract_work_facts(
            {"fact_candidates": [{"fact_id": "fact-1"}]}
        )
        == "resolve_entity_relations"
    )
