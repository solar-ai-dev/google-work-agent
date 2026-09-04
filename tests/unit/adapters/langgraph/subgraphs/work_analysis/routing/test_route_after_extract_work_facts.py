from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_extract_work_facts as route_module,
)


def test_empty_fact__set_skips__relation_provider_calls() -> None:
    assert route_module.route_after_extract_work_facts(
        {"fact_candidates": []}
    ) == "validate_relations"


def test_empty_fact__set_keeps__policy_required_duplicate_analysis() -> None:
    for reason_code in (
        "POLICY_TASK_DUPLICATE_CHECK",
        "POLICY_CALENDAR_CONFLICT_CHECK",
    ):
        state = {
            "fact_candidates": [],
            "tool_route_plan": {
                "input_plan": {"input_routes": [{"reason_codes": [reason_code]}]}
            },
        }

        assert route_module.route_after_extract_work_facts(state) == (
            "detect_duplicate_conflict_candidates"
        )


def test_single_fact__set_skips__relation_provider_calls() -> None:
    assert (
        route_module.route_after_extract_work_facts(
            {"fact_candidates": [{"fact_id": "fact-1"}]}
        )
        == "validate_relations"
    )


def test_two_fact__set_keeps__semantic_relation_analysis() -> None:
    assert (
        route_module.route_after_extract_work_facts(
            {
                "fact_candidates": [
                    {"fact_id": "fact-1", "kind": "TASK"},
                    {"fact_id": "fact-2", "kind": "PERSON"},
                ]
            }
        )
        == "resolve_entity_relations"
    )


def test_non_entity_facts__without_temporal_operand__skip_optional_relation_calls() -> None:
    assert route_module.route_after_extract_work_facts(
        {
            "fact_candidates": [
                {"fact_id": "fact-1", "kind": "TASK"},
                {"fact_id": "fact-2", "kind": "STATUS"},
            ]
        }
    ) == "detect_duplicate_conflict_candidates"


def test_temporal_fact__without_entity_operand__starts_at_temporal_analysis() -> None:
    assert route_module.route_after_extract_work_facts(
        {
            "fact_candidates": [
                {"fact_id": "fact-1", "kind": "TASK"},
                {"fact_id": "fact-2", "kind": "DEADLINE"},
            ]
        }
    ) == "resolve_temporal_dependencies"


def test_policy_only_analysis__routes_directly_to__guarded_responsibility() -> None:
    state = {
        "fact_candidates": [{"fact_id": "fact-1"}, {"fact_id": "fact-2"}],
        "request_intent": {"analysis_requirement": "NONE"},
        "tool_route_plan": {
            "input_plan": {
                "input_routes": [
                    {"reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"]}
                ]
            }
        },
    }

    assert route_module.route_after_extract_work_facts(state) == (
        "detect_duplicate_conflict_candidates"
    )


def test_explicit_analysis__preserves__full_relation_responsibilities() -> None:
    state = {
        "fact_candidates": [
            {"fact_id": "fact-1", "kind": "TASK"},
            {"fact_id": "fact-2", "kind": "PERSON"},
        ],
        "request_intent": {"analysis_requirement": "REQUIRED"},
        "tool_route_plan": {
            "input_plan": {
                "input_routes": [{"reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"]}]
            }
        },
    }

    assert route_module.route_after_extract_work_facts(state) == "resolve_entity_relations"
