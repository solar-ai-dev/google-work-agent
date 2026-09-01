"""Run terminal projection enums and finalize-intent contract."""

from enum import StrEnum
from typing import Literal, NotRequired, Required, TypedDict, cast


class AnalysisResult(StrEnum):
    """Analysis node results."""

    COMPLETE = "COMPLETE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    BLOCKED = "BLOCKED"


class ReviewResult(StrEnum):
    """Review node results."""

    PASS = "PASS"
    REVISE = "REVISE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    ROUTE_RECONSIDERATION = "ROUTE_RECONSIDERATION"
    CONFIRM = "CONFIRM"
    BLOCK = "BLOCK"


class FinalizeIntent(StrEnum):
    """Deterministic terminal intents handed off to Stage 16."""

    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class FinalizeIntentV1(TypedDict):
    """Checkpoint-safe finalize handoff consumed by Stage 16."""

    schema_version: Required[Literal[1]]
    intent: Literal["COMPLETED", "BLOCKED", "FAILED"]
    reason_code: str
    result_kind: NotRequired[Literal["PARTIAL"] | None]


def validate_finalize_intent_v1(value: object) -> FinalizeIntentV1:
    if not isinstance(value, dict):
        raise ValueError("finalize intent must be an object")
    required = {"schema_version", "intent", "reason_code"}
    optional = {"result_kind"}
    actual = set(value)
    missing = required - actual
    extra = actual - required - optional
    if missing:
        raise ValueError(f"finalize intent missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"finalize intent has unsupported fields: {sorted(extra)}")
    schema_version = value["schema_version"]
    if schema_version != 1:
        raise ValueError("finalize intent schema_version must be 1")
    intent = _require_non_empty_string(value["intent"], "intent", "finalize intent")
    if intent not in {item.value for item in FinalizeIntent}:
        raise ValueError("finalize intent intent is invalid")
    reason_code = _require_non_empty_string(value["reason_code"], "reason_code", "finalize intent")
    result_kind = value.get("result_kind")
    if result_kind is not None and result_kind != "PARTIAL":
        raise ValueError("finalize intent result_kind must be PARTIAL or null")
    return {
        "schema_version": 1,
        "intent": cast(Literal["COMPLETED", "BLOCKED", "FAILED"], intent),
        "reason_code": reason_code,
        "result_kind": cast(Literal["PARTIAL"] | None, result_kind),
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
