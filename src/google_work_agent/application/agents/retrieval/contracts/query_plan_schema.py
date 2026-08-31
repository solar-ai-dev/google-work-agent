"""Structured-output schema definition for the canonical RetrievalQueryPlanV2."""

from __future__ import annotations

from google_work_agent.ports.llm import OutputSchemaDefinition

RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="retrieval-query-plan-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "route_queries", "required_information", "retrieval_order"],
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "route_queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "route_id",
                        "operation",
                        "reason_codes",
                        "search_spec",
                        "detail_candidate_ref",
                    ],
                    "properties": {
                        "route_id": {"type": "string"},
                        "operation": {
                            "type": "string",
                            "enum": ["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"],
                        },
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                        "search_spec": {"type": ["object", "null"]},
                        "detail_candidate_ref": {"type": ["string", "null"]},
                    },
                },
            },
            "required_information": {"type": "array", "items": {"type": "string"}},
            "retrieval_order": {"type": "array", "items": {"type": "string"}},
        },
    },
)
