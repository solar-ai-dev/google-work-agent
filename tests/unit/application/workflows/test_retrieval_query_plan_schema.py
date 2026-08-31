from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_v2_output_schema_rejects_legacy_v1_planner_shape() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 1,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation_kind": "SEARCH",
                    "reason_codes": ["MISSING"],
                    "constraint_delta": {"added_constraints": ["invoice"]},
                    "detail_candidate_ref": None,
                }
            ],
            "required_information": ["invoice"],
            "retrieval_order": ["route-1"],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors


def test_v2_output_schema_accepts_v2_root_shape() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": "SEARCH",
                    "reason_codes": ["MISSING"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
            "required_information": ["invoice"],
            "retrieval_order": ["route-1"],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors == []
