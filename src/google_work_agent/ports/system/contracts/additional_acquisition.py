"""Typed request for a cross-agent additional-acquisition handoff."""

from enum import StrEnum
from typing import Literal, Required, TypedDict


class AdditionalAcquisitionOriginResult(StrEnum):
    """Structured retrieval-redirection results understood by the supervisor."""

    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    RETRIEVE_MORE = "RETRIEVE_MORE"


class AdditionalAcquisitionRequestV1(TypedDict):
    """Structured request for another Stage 5 source-planning round."""

    schema_version: Required[Literal[1]]
    origin_phase: str
    origin_result: str
    missing_slots: list[str]
    missing_information: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]


ADDITIONAL_ACQUISITION_ALLOWED_PHASES = frozenset(
    {"CONTEXT_EVALUATION", "WORK_ANALYSIS", "PLAN_REVIEW"}
)


ADDITIONAL_ACQUISITION_ALLOWED_RESULTS = frozenset(
    item.value for item in AdditionalAcquisitionOriginResult
)


def validate_additional_acquisition_request_v1(
    value: object, *, allowed_evidence_refs: set[str] | None = None
) -> AdditionalAcquisitionRequestV1:
    if not isinstance(value, dict):
        raise ValueError("additional acquisition request must be an object")
    required = {
        "schema_version",
        "origin_phase",
        "origin_result",
        "missing_slots",
        "missing_information",
        "evidence_refs",
        "reason_codes",
    }
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(
            f"additional acquisition request missing required fields: {sorted(missing)}"
        )
    if extra:
        raise ValueError(f"additional acquisition request has unsupported fields: {sorted(extra)}")
    schema_version = value["schema_version"]
    if schema_version != 1:
        raise ValueError("additional acquisition request schema_version must be 1")
    origin_phase = _require_string(value["origin_phase"], "origin_phase")
    if origin_phase not in ADDITIONAL_ACQUISITION_ALLOWED_PHASES:
        raise ValueError("additional acquisition request origin_phase is invalid")
    origin_result = _require_string(value["origin_result"], "origin_result")
    if origin_result not in ADDITIONAL_ACQUISITION_ALLOWED_RESULTS:
        raise ValueError("additional acquisition request origin_result is invalid")
    evidence_refs = _require_string_list(value["evidence_refs"], "evidence_refs")
    missing_slots = _require_string_list(value["missing_slots"], "missing_slots")
    missing_information = _require_string_list(value["missing_information"], "missing_information")
    reason_codes = _require_string_list(value["reason_codes"], "reason_codes")
    if not (missing_slots or missing_information or reason_codes):
        raise ValueError(
            "additional acquisition request requires at least one of "
            "missing_slots, missing_information, or reason_codes"
        )
    if allowed_evidence_refs is not None:
        for evidence_ref in evidence_refs:
            if evidence_ref not in allowed_evidence_refs:
                raise ValueError(
                    "additional acquisition request evidence reference does not exist: "
                    f"{evidence_ref}"
                )
    return {
        "schema_version": 1,
        "origin_phase": origin_phase,
        "origin_result": origin_result,
        "missing_slots": missing_slots,
        "missing_information": missing_information,
        "evidence_refs": evidence_refs,
        "reason_codes": reason_codes,
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
