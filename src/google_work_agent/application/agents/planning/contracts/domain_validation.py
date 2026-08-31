"""Planning-result domain validation contract."""

from enum import StrEnum
from typing import Literal, Required, TypedDict, cast


class DomainValidationResult(StrEnum):
    """Domain-validation node results."""

    ALLOW_READ = "ALLOW_READ"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"


class DomainValidationOutputV1(TypedDict):
    """Deterministic domain-validation output consumed by the workflow boundary."""

    schema_version: Required[Literal[1]]
    result: Literal["ALLOW_READ", "REQUIRE_APPROVAL", "BLOCK"]
    reason_codes: list[str]
    blocked_action_ids: list[str]


def validate_domain_validation_output_v1(value: object) -> DomainValidationOutputV1:
    if not isinstance(value, dict):
        raise ValueError("domain validation output must be an object")
    required = {"schema_version", "result", "reason_codes", "blocked_action_ids"}
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"domain validation output missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"domain validation output has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 1:
        raise ValueError("domain validation output schema_version must be 1")
    result = _require_string(value["result"], "result")
    if result not in {item.value for item in DomainValidationResult}:
        raise ValueError("domain validation output result is invalid")
    reason_codes = _require_general_string_list(value["reason_codes"], "reason_codes")
    blocked_action_ids = _require_general_string_list(
        value["blocked_action_ids"], "blocked_action_ids"
    )
    return {
        "schema_version": 1,
        "result": cast(Literal["ALLOW_READ", "REQUIRE_APPROVAL", "BLOCK"], result),
        "reason_codes": reason_codes,
        "blocked_action_ids": blocked_action_ids,
    }


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"additional acquisition request {field_name} must be a string")
    return value


def _require_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"additional acquisition request {field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(
                f"additional acquisition request {field_name}[{index}] must be a string"
            )
        result.append(item)
    return result


def _require_general_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{index}] must be a string")
        result.append(item)
    return result


def _require_non_empty_string(value: object, field_name: str, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} {field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{context} {field_name} must be non-empty")
    return normalized


def _canonical_string_list(
    value: object,
    field_name: str,
    *,
    context: str,
    allow_empty: bool,
    unique: bool,
    sort_values: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{context} {field_name} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        normalized = _require_non_empty_string(item, f"{field_name}[{index}]", context)
        if unique:
            if normalized in seen:
                continue
            seen.add(normalized)
        result.append(normalized)
    if not allow_empty and (not result):
        raise ValueError(f"{context} {field_name} must not be empty")
    if sort_values:
        result.sort()
    return result


def _require_non_negative_int(value: object, field_name: str, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} {field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{context} {field_name} must be non-negative")
    return value


def _require_positive_int(value: object, field_name: str, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} {field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{context} {field_name} must be positive")
    return value
