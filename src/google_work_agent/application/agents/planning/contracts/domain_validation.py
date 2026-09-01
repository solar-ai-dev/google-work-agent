"""Planning-result domain validation contract."""

from enum import StrEnum
from typing import Literal, Required, TypedDict, cast


class DomainValidationResult(StrEnum):
    """Domain-validation node results."""

    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"


class DomainValidationOutputV1(TypedDict):
    """Deterministic domain-validation output consumed by the workflow boundary."""

    schema_version: Required[Literal[1]]
    result: Literal["REQUIRE_APPROVAL", "BLOCK"]
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
        "result": cast(Literal["REQUIRE_APPROVAL", "BLOCK"], result),
        "reason_codes": reason_codes,
        "blocked_action_ids": blocked_action_ids,
    }


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"additional acquisition request {field_name} must be a string")
    return value


def _require_general_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{index}] must be a string")
        result.append(item)
    return result
