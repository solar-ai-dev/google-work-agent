"""Canonical FailureRecordV1 projection and validation.

Product repair/revision prompts receive exactly one normalized failure record.
This module is the single runtime projector/validator for that nested DTO; node
callers may supply local diagnostics to choose the canonical fields, but may
not add bespoke prompt fields.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Literal, TypedDict, cast

FailureOriginV1 = Literal[
    "LLM_OUTPUT",
    "QUERY_PLANNING",
    "RETRIEVAL_RESULT",
    "PROVIDER",
    "DOMAIN",
    "POLICY",
    "EXPERIMENT",
]
DetectedByV1 = Literal[
    "RUNTIME_SCHEMA_VALIDATOR",
    "RUNTIME_DOMAIN_VALIDATOR",
    "RUNTIME_POLICY_VALIDATOR",
    "RUNTIME_REVIEW_AGENT",
    "RUNTIME_PROVIDER",
    "EXPERIMENT_DETERMINISTIC_GRADER",
    "EXPERIMENT_SEMANTIC_GRADER",
    "HUMAN_REVIEW",
]
RuntimeDispositionV1 = Literal[
    "RETRYABLE",
    "REDIRECT",
    "DETERMINISTIC",
    "TERMINAL",
    "NOT_AVAILABLE",
]
ExperimentDispositionV1 = Literal[
    "COUNT_FAILURE",
    "RUN_REPAIR",
    "RUN_REVISION",
    "REJECT_CANDIDATE",
    "HUMAN_REVIEW",
]


class FailureRecordV1(TypedDict):
    schema_version: Literal[1]
    failure_id: str
    failure_reason_code: str
    failure_origin: FailureOriginV1
    detected_by: DetectedByV1
    runtime_disposition: RuntimeDispositionV1
    experiment_disposition: ExperimentDispositionV1
    affected_field_paths: list[str]
    evidence_refs: list[str]


FAILURE_RECORD_FIELDS = frozenset(FailureRecordV1.__annotations__)
_FAILURE_ORIGINS = {
    "LLM_OUTPUT",
    "QUERY_PLANNING",
    "RETRIEVAL_RESULT",
    "PROVIDER",
    "DOMAIN",
    "POLICY",
    "EXPERIMENT",
}
_DETECTED_BY = {
    "RUNTIME_SCHEMA_VALIDATOR",
    "RUNTIME_DOMAIN_VALIDATOR",
    "RUNTIME_POLICY_VALIDATOR",
    "RUNTIME_REVIEW_AGENT",
    "RUNTIME_PROVIDER",
    "EXPERIMENT_DETERMINISTIC_GRADER",
    "EXPERIMENT_SEMANTIC_GRADER",
    "HUMAN_REVIEW",
}
_RUNTIME_DISPOSITIONS = {
    "RETRYABLE",
    "REDIRECT",
    "DETERMINISTIC",
    "TERMINAL",
    "NOT_AVAILABLE",
}
_EXPERIMENT_DISPOSITIONS = {
    "COUNT_FAILURE",
    "RUN_REPAIR",
    "RUN_REVISION",
    "REJECT_CANDIDATE",
    "HUMAN_REVIEW",
}


class FailureRecordValidationError(ValueError):
    pass


def build_failure_record_v1(
    *,
    failure_reason_code: str,
    failure_origin: FailureOriginV1,
    detected_by: DetectedByV1,
    runtime_disposition: RuntimeDispositionV1,
    experiment_disposition: ExperimentDispositionV1,
    affected_field_paths: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    failure_context_ids: Iterable[str] = (),
    failure_id: str | None = None,
) -> FailureRecordV1:
    """Project local failure diagnostics into the canonical prompt DTO.

    ``failure_context_ids`` may bind a deterministic id to local issue ids but
    is never serialized into the Product Prompt.
    """

    paths = _dedupe_non_empty(affected_field_paths, "affected_field_paths")
    refs = _dedupe_non_empty(evidence_refs, "evidence_refs")
    context_ids = _dedupe_non_empty(failure_context_ids, "failure_context_ids")
    if failure_id is None:
        identity = json.dumps(
            {
                "failure_reason_code": failure_reason_code,
                "failure_origin": failure_origin,
                "detected_by": detected_by,
                "affected_field_paths": paths,
                "evidence_refs": refs,
                "failure_context_ids": context_ids,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        failure_id = f"failure-{hashlib.sha256(identity).hexdigest()[:24]}"
    record: FailureRecordV1 = {
        "schema_version": 1,
        "failure_id": failure_id,
        "failure_reason_code": failure_reason_code,
        "failure_origin": failure_origin,
        "detected_by": detected_by,
        "runtime_disposition": runtime_disposition,
        "experiment_disposition": experiment_disposition,
        "affected_field_paths": paths,
        "evidence_refs": refs,
    }
    return validate_failure_record_v1(record)


def validate_failure_record_v1(value: object) -> FailureRecordV1:
    if not isinstance(value, Mapping):
        raise FailureRecordValidationError("failure_record must be an object")
    root = cast(Mapping[str, object], value)
    keys = set(root)
    if keys != FAILURE_RECORD_FIELDS:
        missing = sorted(FAILURE_RECORD_FIELDS - keys)
        extra = sorted(keys - FAILURE_RECORD_FIELDS)
        raise FailureRecordValidationError(
            f"failure_record exact schema mismatch; missing={missing}, extra={extra}"
        )
    if root["schema_version"] != 1 or isinstance(root["schema_version"], bool):
        raise FailureRecordValidationError("failure_record.schema_version must be 1")
    _non_empty_string(root["failure_id"], "failure_id")
    _non_empty_string(root["failure_reason_code"], "failure_reason_code")
    _enum(root["failure_origin"], "failure_origin", _FAILURE_ORIGINS)
    _enum(root["detected_by"], "detected_by", _DETECTED_BY)
    _enum(root["runtime_disposition"], "runtime_disposition", _RUNTIME_DISPOSITIONS)
    _enum(
        root["experiment_disposition"],
        "experiment_disposition",
        _EXPERIMENT_DISPOSITIONS,
    )
    paths = _string_list(root["affected_field_paths"], "affected_field_paths")
    refs = _string_list(root["evidence_refs"], "evidence_refs")
    return {
        "schema_version": 1,
        "failure_id": cast(str, root["failure_id"]),
        "failure_reason_code": cast(str, root["failure_reason_code"]),
        "failure_origin": cast(FailureOriginV1, root["failure_origin"]),
        "detected_by": cast(DetectedByV1, root["detected_by"]),
        "runtime_disposition": cast(RuntimeDispositionV1, root["runtime_disposition"]),
        "experiment_disposition": cast(ExperimentDispositionV1, root["experiment_disposition"]),
        "affected_field_paths": paths,
        "evidence_refs": refs,
    }


def _dedupe_non_empty(values: Iterable[str], field: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise FailureRecordValidationError(f"{field} items must be non-empty strings")
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise FailureRecordValidationError(f"failure_record.{field} must be an array")
    result = _dedupe_non_empty(value, field)
    if len(result) != len(value):
        raise FailureRecordValidationError(f"failure_record.{field} must be unique")
    return result


def _non_empty_string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise FailureRecordValidationError(f"failure_record.{field} must be a non-empty string")


def _enum(value: object, field: str, allowed: set[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise FailureRecordValidationError(f"failure_record.{field} is invalid")


__all__ = [
    "FAILURE_RECORD_FIELDS",
    "FailureRecordV1",
    "FailureRecordValidationError",
    "build_failure_record_v1",
    "validate_failure_record_v1",
]
