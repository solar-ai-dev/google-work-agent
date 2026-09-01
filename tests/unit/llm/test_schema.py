"""Unit tests for the shared structured-output shape validator.

No test file previously covered ``validate_output_schema`` directly; the
type-union branch (``{"type": ["string", "null"]}``, used by every node's
nullable fields) was a silent no-op before this fix (see Node Contract
Audit) -- these tests lock in the corrected behavior.
"""

from __future__ import annotations

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


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


# --- Batch B (0~6 stage audit): active runtime Prompt Output Schemas use
# several JSON Schema keywords the shared validator did not previously
# enforce at all (declared but silently unchecked). Each keyword below is
# one actually used somewhere in this repository's schemas -- see
# planning_tool_schemas.py, planning_argument_writer.py, Retrieval schemas,
# tool_route_semantic.py, request_understanding.py, solution_planning.py.


def test_const_accepts_matching_value_and_rejects_mismatch() -> None:
    schema = {"const": "CALENDAR"}
    assert validate_output_schema("CALENDAR", schema) == []
    assert validate_output_schema("GMAIL", schema) == ["$ must equal 'CALENDAR'"]


def test_const_none_accepts_null_and_rejects_non_null() -> None:
    schema = {"const": None}
    assert validate_output_schema(None, schema) == []
    assert validate_output_schema("x", schema) == ["$ must equal None"]


def test_one_of_accepts_exactly_one_match_and_rejects_zero_or_many() -> None:
    schema = {"oneOf": [{"type": "null"}, {"type": "string", "minLength": 1}]}
    assert validate_output_schema(None, schema) == []
    assert validate_output_schema("ok", schema) == []
    assert validate_output_schema(3, schema) == [
        "$ must match exactly one schema in oneOf (matched 0)"
    ]


def test_all_of_requires_every_subschema_to_pass() -> None:
    schema = {
        "allOf": [
            {"type": "string", "minLength": 3},
            {"type": "string", "pattern": "^[a-z]+$"},
        ]
    }
    assert validate_output_schema("abcd", schema) == []
    errors = validate_output_schema("AB", schema)
    assert errors == [
        "$ must be at least 3 characters",
        "$ must match pattern ^[a-z]+$",
    ]


def test_if_then_applies_then_only_when_if_matches() -> None:
    schema = {
        "type": "object",
        "if": {"properties": {"source": {"enum": ["GMAIL", "TASKS"]}}},
        "then": {"properties": {"calendar_read_mode": {"const": None}}},
    }
    assert validate_output_schema({"source": "GMAIL", "calendar_read_mode": None}, schema) == []
    assert validate_output_schema(
        {"source": "GMAIL", "calendar_read_mode": "EVENTS_ONLY"}, schema
    ) == ["$.calendar_read_mode must equal None"]
    # "if" does not match (source is CALENDAR) -- "then" is skipped, so an
    # unrelated calendar_read_mode value is not an error here.
    assert (
        validate_output_schema({"source": "CALENDAR", "calendar_read_mode": "EVENTS_ONLY"}, schema)
        == []
    )


def test_min_length_rejects_short_strings() -> None:
    schema = {"type": "string", "minLength": 1}
    assert validate_output_schema("a", schema) == []
    assert validate_output_schema("", schema) == ["$ must be at least 1 characters"]


def test_pattern_rejects_non_matching_strings() -> None:
    schema = {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"}
    assert validate_output_schema("a" * 64, schema) == []
    assert validate_output_schema("not-a-hash", schema) == [
        "$ must match pattern ^[0-9a-fA-F]{64}$"
    ]


def test_format_date_rejects_non_iso_dates() -> None:
    schema = {"type": "string", "format": "date"}
    assert validate_output_schema("2026-08-20", schema) == []
    assert validate_output_schema("08/20/2026", schema) == [
        "$ must be an ISO 8601 date (YYYY-MM-DD)"
    ]


def test_min_items_and_max_items_bound_array_length() -> None:
    schema = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2}
    assert validate_output_schema(["a"], schema) == []
    assert validate_output_schema([], schema) == ["$ must contain at least 1 items"]
    assert validate_output_schema(["a", "b", "c"], schema) == ["$ must contain at most 2 items"]


def test_unique_items_rejects_duplicates() -> None:
    schema = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    assert validate_output_schema(["a", "b"], schema) == []
    assert validate_output_schema(["a", "a"], schema) == ["$ items must be unique"]


def test_minimum_rejects_values_below_bound() -> None:
    schema = {"type": "integer", "minimum": 1}
    assert validate_output_schema(1, schema) == []
    assert validate_output_schema(0, schema) == ["$ must be >= 1"]


def test_min_properties_rejects_too_few_properties() -> None:
    schema = {"type": "object", "minProperties": 1}
    assert validate_output_schema({"a": 1}, schema) == []
    assert validate_output_schema({}, schema) == ["$ must have at least 1 properties"]
