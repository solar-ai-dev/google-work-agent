"""Small JSON schema validator for structured provider output."""

from __future__ import annotations

from collections.abc import Mapping


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
        if expected_type == "object":
            if not isinstance(value, dict):
                errors.append(f"{path} must be an object")
                return
            _validate_object(value=value, schema=schema, path=path, errors=errors)
            return
        if expected_type == "array":
            if not isinstance(value, list):
                errors.append(f"{path} must be an array")
                return
            item_schema = schema.get("items")
            if isinstance(item_schema, Mapping):
                for index, item in enumerate(value):
                    _validate(
                        value=item,
                        schema=item_schema,
                        path=f"{path}[{index}]",
                        errors=errors,
                    )
            return
        if not _matches_scalar_type(value=value, expected_type=expected_type):
            errors.append(f"{path} must be {expected_type}")
            return
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"{path} must be one of {enum_values}")


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
