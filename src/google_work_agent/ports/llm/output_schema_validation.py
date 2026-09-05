"""Boundary-local JSON schema validator for structured provider output.

Supports exactly the JSON Schema keywords the repository's active runtime
Prompt Output Schemas actually declare (``type`` incl. type unions,
``enum``, ``const``, ``oneOf``, ``allOf``, ``if``/``then``/``else``,
object ``properties``/``required``/``additionalProperties``/
``minProperties``, array ``items``/``minItems``/``maxItems``/
``uniqueItems``/``contains``, string ``minLength``/``pattern``/``format: date``, and
numeric ``minimum``) -- not the full JSON Schema standard. Extending this
should be usage-driven: add a keyword only once an active schema in this
repository actually declares it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import cast


def validate_output_schema(value: object, schema: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    _validate(value=value, schema=schema, path="$", errors=errors)
    return errors


def _validate(
    *,
    value: object,
    schema: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        _validate_single_type(
            value=value, schema=schema, expected_type=expected_type, path=path, errors=errors
        )
    elif isinstance(expected_type, list):
        _validate_type_union(
            value=value, schema=schema, expected_types=expected_type, path=path, errors=errors
        )

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"{path} must be one of {enum_values}")

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")

    # Object-shaped constraints apply whenever the instance is an object,
    # independent of whether "type": "object" was declared -- conditional
    # ``if``/``then`` fragments in this repo's schemas only declare
    # "properties", never "type".
    if isinstance(value, dict) and (
        "properties" in schema
        or "required" in schema
        or "additionalProperties" in schema
        or "minProperties" in schema
    ):
        _validate_object(value=value, schema=schema, path=path, errors=errors)
    # Conditional and composed JSON Schema fragments commonly refine an
    # already-declared array with only minItems/maxItems/uniqueItems. Those
    # constraints still apply even when the fragment does not repeat type.
    if isinstance(value, list) and expected_type != "array" and any(
        keyword in schema
        for keyword in ("items", "minItems", "maxItems", "uniqueItems", "contains")
    ):
        _validate_array_constraints(value=value, schema=schema, path=path, errors=errors)

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        _validate_one_of(value=value, subschemas=one_of, path=path, errors=errors)

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for subschema in all_of:
            if isinstance(subschema, Mapping):
                _validate(value=value, schema=subschema, path=path, errors=errors)

    if_schema = schema.get("if")
    if isinstance(if_schema, Mapping):
        _validate_if_then(
            value=value,
            if_schema=if_schema,
            then_schema=schema.get("then"),
            else_schema=schema.get("else"),
            path=path,
            errors=errors,
        )


def _errors_for(*, value: object, schema: Mapping[str, object], path: str) -> list[str]:
    sub_errors: list[str] = []
    _validate(value=value, schema=schema, path=path, errors=sub_errors)
    return sub_errors


def _validate_one_of(
    *, value: object, subschemas: list[object], path: str, errors: list[str]
) -> None:
    matches = sum(
        1
        for subschema in subschemas
        if isinstance(subschema, Mapping)
        and not _errors_for(value=value, schema=subschema, path=path)
    )
    if matches != 1:
        errors.append(f"{path} must match exactly one schema in oneOf (matched {matches})")


def _validate_if_then(
    *,
    value: object,
    if_schema: Mapping[str, object],
    then_schema: object,
    else_schema: object,
    path: str,
    errors: list[str],
) -> None:
    if _errors_for(value=value, schema=if_schema, path=path):
        if isinstance(else_schema, Mapping):
            _validate(value=value, schema=else_schema, path=path, errors=errors)
        return
    if isinstance(then_schema, Mapping):
        _validate(value=value, schema=then_schema, path=path, errors=errors)


def _validate_single_type(
    *,
    value: object,
    schema: Mapping[str, object],
    expected_type: str,
    path: str,
    errors: list[str],
) -> None:
    if expected_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path} must be an object")
        return
    if expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path} must be an array")
            return
        _validate_array_constraints(value=value, schema=schema, path=path, errors=errors)
        return
    if not _matches_scalar_type(value=value, expected_type=expected_type):
        errors.append(f"{path} must be {expected_type}")
        return
    if expected_type == "string":
        _validate_string_constraints(value=str(value), schema=schema, path=path, errors=errors)
    elif expected_type in ("integer", "number"):
        _validate_numeric_constraints(
            value=float(cast(str | int | float, value)),
            schema=schema,
            path=path,
            errors=errors,
        )


def _validate_type_union(
    *,
    value: object,
    schema: Mapping[str, object],
    expected_types: list[object],
    path: str,
    errors: list[str],
) -> None:
    for candidate in expected_types:
        if not isinstance(candidate, str):
            continue
        if _value_matches_type(value=value, expected_type=candidate):
            _validate_single_type(
                value=value, schema=schema, expected_type=candidate, path=path, errors=errors
            )
            return
    errors.append(f"{path} must be one of types {expected_types}")


def _value_matches_type(*, value: object, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return _matches_scalar_type(value=value, expected_type=expected_type)


def _validate_object(
    *,
    value: dict[object, object],
    schema: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    properties = schema.get("properties")
    required = schema.get("required")
    known_properties = properties if isinstance(properties, Mapping) else {}
    required_fields = required if isinstance(required, list) else []
    for field in required_fields:
        if isinstance(field, str) and field not in value:
            errors.append(f"{path}.{field} is required")
    min_properties = schema.get("minProperties")
    if isinstance(min_properties, int) and len(value) < min_properties:
        errors.append(f"{path} must have at least {min_properties} properties")
    additional_allowed = schema.get("additionalProperties", True)
    for key, item in value.items():
        if not isinstance(key, str):
            errors.append(f"{path} keys must be strings")
            continue
        child_schema = known_properties.get(key)
        if child_schema is None:
            if additional_allowed is False:
                errors.append(f"{path}.{key} is not allowed")
            continue
        if isinstance(child_schema, Mapping):
            _validate(value=item, schema=child_schema, path=f"{path}.{key}", errors=errors)


def _validate_array_constraints(
    *,
    value: list[object],
    schema: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    item_schema = schema.get("items")
    if isinstance(item_schema, Mapping):
        for index, item in enumerate(value):
            _validate(value=item, schema=item_schema, path=f"{path}[{index}]", errors=errors)
    min_items = schema.get("minItems")
    contains = schema.get("contains")
    if isinstance(contains, Mapping) and not any(
        not _errors_for(value=item, schema=contains, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    ):
        errors.append(f"{path} must contain an item matching contains")
    if isinstance(min_items, int) and len(value) < min_items:
        errors.append(f"{path} must contain at least {min_items} items")
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(value) > max_items:
        errors.append(f"{path} must contain at most {max_items} items")
    if schema.get("uniqueItems") is True:
        seen: list[object] = []
        for item in value:
            if item in seen:
                errors.append(f"{path} items must be unique")
                break
            seen.append(item)


def _validate_string_constraints(
    *,
    value: str,
    schema: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    min_length = schema.get("minLength")
    if isinstance(min_length, int) and len(value) < min_length:
        errors.append(f"{path} must be at least {min_length} characters")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        errors.append(f"{path} must match pattern {pattern}")
    format_name = schema.get("format")
    if format_name == "date" and not _is_iso_date(value):
        errors.append(f"{path} must be an ISO 8601 date (YYYY-MM-DD)")


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_numeric_constraints(
    *,
    value: float,
    schema: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    minimum = schema.get("minimum")
    if isinstance(minimum, int | float) and value < minimum:
        errors.append(f"{path} must be >= {minimum}")


def _matches_scalar_type(*, value: object, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True
