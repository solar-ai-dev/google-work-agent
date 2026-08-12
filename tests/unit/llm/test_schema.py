"""Unit tests for the shared structured-output shape validator.

No test file previously covered ``validate_output_schema`` directly; the
type-union branch (``{"type": ["string", "null"]}``, used by every node's
nullable fields) was a silent no-op before this fix (see Node Contract
Audit) -- these tests lock in the corrected behavior.
"""

from __future__ import annotations

from google_work_agent.adapters.llm.schema import validate_output_schema


def test_type_union_accepts_either_listed_type() -> None:
    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": ["string", "null"]}},
    }
    assert validate_output_schema({"x": "hello"}, schema) == []
    assert validate_output_schema({"x": None}, schema) == []


def test_type_union_rejects_a_value_matching_neither_listed_type() -> None:
    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": ["string", "null"]}},
    }
    errors = validate_output_schema({"x": 123}, schema)
    assert errors == ["$.x must be one of types ['string', 'null']"]


def test_type_union_rejects_wrong_type_in_array_items() -> None:
    schema = {
        "type": "object",
        "required": ["items"],
        "properties": {"items": {"type": "array", "items": {"type": ["integer", "null"]}}},
    }
    errors = validate_output_schema({"items": [1, "two", None]}, schema)
    assert errors == ["$.items[1] must be one of types ['integer', 'null']"]


def test_object_or_null_union_still_validates_nested_properties_when_object() -> None:
    schema = {
        "type": "object",
        "required": ["confirmation"],
        "properties": {
            "confirmation": {
                "type": ["object", "null"],
                "required": ["question"],
                "properties": {"question": {"type": "string"}},
            }
        },
    }
    assert validate_output_schema({"confirmation": None}, schema) == []
    assert validate_output_schema({"confirmation": {"question": "ok?"}}, schema) == []
    errors = validate_output_schema({"confirmation": {}}, schema)
    assert errors == ["$.confirmation.question is required"]


def test_object_or_null_union_rejects_non_object_non_null() -> None:
    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": ["object", "null"]}},
    }
    errors = validate_output_schema({"x": "not-an-object"}, schema)
    assert errors == ["$.x must be one of types ['object', 'null']"]
