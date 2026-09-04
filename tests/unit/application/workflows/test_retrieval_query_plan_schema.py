import pytest

from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    bind_retrieval_query_plan_output_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


def test_v2_output__schema_rejects_legacy__v1_planner_shape() -> None:
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


def test_v2_output__schema_accepts__v2_root_shape() -> None:
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


def test_constraint_union__rejects_extra_fields__for_declared_kind() -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "calendar-read",
                    "operation": "SEARCH",
                    "reason_codes": ["POLICY_PRECONDITION"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {
                                "kind": "CONTAINER_REF",
                                "container_refs": ["calendar:primary"],
                                "calendar_id": "primary",
                            }
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
            "required_information": ["calendar conflicts"],
            "retrieval_order": ["calendar-read"],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors


def test_runtime_binding__rejects_unvalidated__container_ref() -> None:
    schema = bind_retrieval_query_plan_output_schema(
        route_ids=["calendar-read"],
        supported_constraint_kinds={
            "calendar-read": ["TEMPORAL_RANGE", "CONTAINER_REF"]
        },
        validated_container_refs={"calendar-read": ["primary"]},
    )
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": ["calendar:primary"]}
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["calendar conflicts"],
        "retrieval_order": ["calendar-read"],
    }

    assert validate_output_schema(candidate, schema.json_schema)
    candidate["route_queries"][0]["search_spec"]["constraints"][0]["container_refs"] = [
        "primary"
    ]
    assert validate_output_schema(candidate, schema.json_schema) == []


def test_temporal_constraint__rejects_offset_bearing__local_value() -> None:
    candidate = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "EVENT_TIME",
                            "start_local": "2026-09-05T15:00:00+09:00",
                            "end_local": "2026-09-05T15:30:00+09:00",
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["calendar conflicts"],
        "retrieval_order": ["calendar-read"],
    }

    assert validate_output_schema(candidate, RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema)


@pytest.mark.parametrize(
    ("operation", "search_spec", "detail_candidate_ref"),
    [
        ("SEARCH", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("FREEBUSY", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("DETAIL_FETCH", {"mode": "INITIAL", "constraints": []}, "candidate-1"),
        ("NEXT_PAGE", {"mode": "INITIAL", "constraints": []}, None),
        ("NEXT_PAGE", None, "candidate-1"),
    ],
)
def test_operation_union__with_mismatched_fields__rejects_candidate(
    operation: str,
    search_spec: object,
    detail_candidate_ref: str | None,
) -> None:
    errors = validate_output_schema(
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "route-1",
                    "operation": operation,
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": search_spec,
                    "detail_candidate_ref": detail_candidate_ref,
                }
            ],
            "required_information": ["mail"],
            "retrieval_order": ["route-1"],
        },
        RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA.json_schema,
    )

    assert errors
