"""Provider-friendly structured-output shape for RetrievalQueryPlanV2."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

_CONSTRAINT_KINDS = [
    "TEMPORAL_RANGE",
    "PARTICIPANT",
    "KEYWORD",
    "RESOURCE_REF",
    "CONTAINER_REF",
    "STATUS_SCOPE",
]
_NON_EMPTY_STRING = {"type": "string", "minLength": 1}
_LOCAL_ISO_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"
)

_CONSTRAINT_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "axis", "start_local", "end_local", "timezone"],
            "properties": {
                "kind": {"const": "TEMPORAL_RANGE"},
                "axis": {
                    "enum": [
                        "MESSAGE_TIME",
                        "TASK_SCHEDULED_DATE",
                        "EVENT_TIME",
                        "AVAILABILITY_WINDOW",
                    ]
                },
                "start_local": {"type": ["string", "null"], "pattern": _LOCAL_ISO_PATTERN},
                "end_local": {"type": ["string", "null"], "pattern": _LOCAL_ISO_PATTERN},
                "timezone": _NON_EMPTY_STRING,
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "participants", "match_mode"],
            "properties": {
                "kind": {"const": "PARTICIPANT"},
                "participants": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["role", "identity"],
                        "properties": {
                            "role": {"enum": ["ANY", "SENDER", "RECIPIENT", "ATTENDEE"]},
                            "identity": _NON_EMPTY_STRING,
                        },
                    },
                },
                "match_mode": {"enum": ["ANY", "ALL"]},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "terms", "match_mode"],
            "properties": {
                "kind": {"const": "KEYWORD"},
                "terms": {"type": "array", "minItems": 1, "items": _NON_EMPTY_STRING},
                "match_mode": {"enum": ["ANY", "ALL", "PHRASE"]},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "resource_refs"],
            "properties": {
                "kind": {"const": "RESOURCE_REF"},
                "resource_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": _NON_EMPTY_STRING,
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "container_refs"],
            "properties": {
                "kind": {"const": "CONTAINER_REF"},
                "container_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": _NON_EMPTY_STRING,
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "values"],
            "properties": {
                "kind": {"const": "STATUS_SCOPE"},
                "values": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "enum": [
                            "ANY",
                            "INCOMPLETE",
                            "COMPLETED",
                            "DRAFT",
                            "SENT",
                            "CANCELLED",
                            "CONFIRMED",
                            "TENTATIVE",
                        ]
                    },
                },
            },
        },
    ]
}

_INITIAL_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraints"],
    "properties": {
        "mode": {"const": "INITIAL"},
        "constraints": {"type": "array", "items": _CONSTRAINT_SCHEMA},
    },
}
_CHANGED_SEARCH_SPEC = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "constraint_delta"],
    "properties": {
        "mode": {"const": "CHANGED"},
        "constraint_delta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["upsert_constraints", "remove_constraint_kinds"],
            "properties": {
                "upsert_constraints": {"type": "array", "items": _CONSTRAINT_SCHEMA},
                "remove_constraint_kinds": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": _CONSTRAINT_KINDS},
                },
            },
        },
    },
}


def _route_query_schema(
    operation: str,
    *,
    search_spec: Mapping[str, object],
    detail_candidate_ref: Mapping[str, object],
) -> dict[str, object]:
    return {
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
            "route_id": _NON_EMPTY_STRING,
            "operation": {"const": operation},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _NON_EMPTY_STRING,
            },
            "search_spec": search_spec,
            "detail_candidate_ref": detail_candidate_ref,
        },
    }


_SEARCH_SPEC = {"oneOf": [_INITIAL_SEARCH_SPEC, _CHANGED_SEARCH_SPEC]}
_NULL = {"type": "null"}
_ROUTE_QUERY_SCHEMA = {
    "oneOf": [
        _route_query_schema("SEARCH", search_spec=_SEARCH_SPEC, detail_candidate_ref=_NULL),
        _route_query_schema("FREEBUSY", search_spec=_SEARCH_SPEC, detail_candidate_ref=_NULL),
        _route_query_schema("NEXT_PAGE", search_spec=_NULL, detail_candidate_ref=_NULL),
        _route_query_schema(
            "DETAIL_FETCH",
            search_spec=_NULL,
            detail_candidate_ref=_NON_EMPTY_STRING,
        ),
    ]
}

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
                "minItems": 1,
                "items": _ROUTE_QUERY_SCHEMA,
            },
            "required_information": {
                "type": "array",
                "minItems": 1,
                "items": _NON_EMPTY_STRING,
            },
            "retrieval_order": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _NON_EMPTY_STRING,
            },
        },
    },
)


def bind_retrieval_query_plan_output_schema(
    *,
    base_schema: OutputSchemaDefinition = RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
    route_ids: Collection[str],
    supported_constraint_kinds: Mapping[str, Collection[str]] | None = None,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
) -> OutputSchemaDefinition:
    """Bind planner-generated identities to values validated in the current state."""

    json_schema = deepcopy(base_schema.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    route_queries = cast(dict[str, object], properties["route_queries"])
    retrieval_order = cast(dict[str, object], properties["retrieval_order"])
    allowed_route_ids = sorted(set(route_ids))
    retrieval_order["items"] = {"type": "string", "enum": allowed_route_ids}

    allowed_resource_refs = _flatten_refs(validated_resource_refs)
    allowed_container_refs = _flatten_refs(validated_container_refs)
    allowed_constraint_kinds = {
        kind for kinds in (supported_constraint_kinds or {}).values() for kind in kinds
    }
    for operation_schema in cast(
        list[dict[str, object]], cast(dict[str, object], route_queries["items"])["oneOf"]
    ):
        operation_properties = cast(dict[str, object], operation_schema["properties"])
        operation_properties["route_id"] = {
            "type": "string",
            "enum": allowed_route_ids,
        }
        if cast(dict[str, object], operation_properties["operation"])["const"] == "DETAIL_FETCH":
            candidates = sorted(set(detail_candidate_refs))
            if candidates:
                operation_properties["detail_candidate_ref"] = {
                    "type": "string",
                    "enum": candidates,
                }
        _bind_constraint_ref_values(
            operation_properties["search_spec"],
            allowed_constraint_kinds=allowed_constraint_kinds,
            allowed_resource_refs=allowed_resource_refs,
            allowed_container_refs=allowed_container_refs,
        )
    return OutputSchemaDefinition(
        schema_version=base_schema.schema_version,
        json_schema=json_schema,
    )


def _flatten_refs(values: Mapping[str, Collection[str]] | None) -> list[str]:
    return sorted({item for refs in (values or {}).values() for item in refs})


def _bind_constraint_ref_values(
    value: object,
    *,
    allowed_constraint_kinds: set[str],
    allowed_resource_refs: list[str],
    allowed_container_refs: list[str],
) -> None:
    if isinstance(value, list):
        for item in value:
            _bind_constraint_ref_values(
                item,
                allowed_constraint_kinds=allowed_constraint_kinds,
                allowed_resource_refs=allowed_resource_refs,
                allowed_container_refs=allowed_container_refs,
            )
        return
    if not isinstance(value, dict):
        return
    options = value.get("oneOf")
    if isinstance(options, list) and allowed_constraint_kinds:
        declared_kinds = [_declared_constraint_kind(item) for item in options]
        if declared_kinds and all(kind is not None for kind in declared_kinds):
            value["oneOf"] = [
                item
                for item, kind in zip(options, declared_kinds, strict=True)
                if kind in allowed_constraint_kinds
            ]
    properties = value.get("properties")
    if isinstance(properties, dict):
        kind_schema = properties.get("kind")
        kind = kind_schema.get("const") if isinstance(kind_schema, dict) else None
        if kind == "RESOURCE_REF" and allowed_resource_refs:
            refs = properties.get("resource_refs")
            if isinstance(refs, dict):
                refs["items"] = {"type": "string", "enum": allowed_resource_refs}
        if kind == "CONTAINER_REF" and allowed_container_refs:
            refs = properties.get("container_refs")
            if isinstance(refs, dict):
                refs["items"] = {"type": "string", "enum": allowed_container_refs}
    for child in value.values():
        _bind_constraint_ref_values(
            child,
            allowed_constraint_kinds=allowed_constraint_kinds,
            allowed_resource_refs=allowed_resource_refs,
            allowed_container_refs=allowed_container_refs,
        )


def _declared_constraint_kind(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    properties = value.get("properties")
    if not isinstance(properties, dict):
        return None
    kind_schema = properties.get("kind")
    if not isinstance(kind_schema, dict):
        return None
    kind = kind_schema.get("const")
    return kind if isinstance(kind, str) else None
