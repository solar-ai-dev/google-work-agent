"""Atomic Review inspection contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, TypedDict, cast

from google_work_agent.ports.llm import OutputSchemaDefinition

ReviewDimensionIdV1 = Literal[
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
]
ReviewFindingKindV1 = Literal[
    "ISSUE",
    "EVIDENCE_GAP",
    "ROUTE_ISSUE",
    "CONFIRMATION",
    "BLOCKER",
]

# Legacy aggregate/recheck input contracts remain owned by #120.  Keep them
# distinct from the atomic inspector contract so this slice does not migrate
# the downstream final-disposition authority early.
ReviewDimension = Literal["GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"]


class AtomicReviewFindingV1(TypedDict):
    dimension: ReviewDimension
    code: str
    description: str
    action_id: str | None
    route_id: str | None
    required_information: list[str]


class ReviewInspectorFindingV1(TypedDict):
    dimension: ReviewDimensionIdV1
    code: str
    finding_kind: ReviewFindingKindV1
    description: str
    evidence_refs: list[str]
    affected_action_ids: list[str]
    affected_route_ids: list[str]
    required_information: list[str]


class ReviewInspectorResultV1(TypedDict):
    schema_version: Literal[1]
    dimension: ReviewDimensionIdV1
    findings: list[ReviewInspectorFindingV1]


class RecheckAffectedDimensionsResultV1(TypedDict):
    affected_dimensions: tuple[ReviewDimension, ...]
    findings: tuple[AtomicReviewFindingV1, ...]


class ReviewSemanticInvoker(Protocol):
    def __call__(
        self,
        prompt_id: str,
        prompt_input: Mapping[str, object],
    ) -> Mapping[str, object]: ...


def review_inspector_output_schema(
    dimension: ReviewDimensionIdV1,
) -> OutputSchemaDefinition:
    """Return the closed structured-output schema for one inspector dimension."""
    string_array = {"type": "array", "items": {"type": "string"}}
    return OutputSchemaDefinition(
        schema_version=f"{dimension}-result-v1",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "dimension", "findings"],
            "properties": {
                "schema_version": {"const": 1},
                "dimension": {"const": dimension},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "dimension",
                            "code",
                            "finding_kind",
                            "description",
                            "evidence_refs",
                            "affected_action_ids",
                            "affected_route_ids",
                            "required_information",
                        ],
                        "properties": {
                            "dimension": {"const": dimension},
                            "code": {"type": "string", "minLength": 1},
                            "finding_kind": {
                                "enum": [
                                    "ISSUE",
                                    "EVIDENCE_GAP",
                                    "ROUTE_ISSUE",
                                    "CONFIRMATION",
                                    "BLOCKER",
                                ]
                            },
                            "description": {"type": "string", "minLength": 1},
                            "evidence_refs": string_array,
                            "affected_action_ids": string_array,
                            "affected_route_ids": string_array,
                            "required_information": string_array,
                        },
                    },
                },
            },
        },
    )


def validate_review_inspector_result(
    value: object,
    *,
    expected_dimension: ReviewDimensionIdV1,
) -> ReviewInspectorResultV1:
    """Fail closed on free-form dimensions, fields, and final dispositions."""
    if not isinstance(value, Mapping):
        raise ValueError("ReviewInspectorResultV1 must be an object")
    root = dict(value)
    if set(root) != {"schema_version", "dimension", "findings"}:
        raise ValueError("ReviewInspectorResultV1 keys do not match contract")
    if (
        not isinstance(root["schema_version"], int)
        or isinstance(root["schema_version"], bool)
        or root["schema_version"] != 1
    ):
        raise ValueError("ReviewInspectorResultV1.schema_version must be 1")
    if root["dimension"] != expected_dimension:
        raise ValueError("Review inspector returned an invalid dimension")
    raw_findings = root["findings"]
    if not isinstance(raw_findings, list):
        raise ValueError("ReviewInspectorResultV1.findings must be a list")

    findings: list[ReviewInspectorFindingV1] = []
    expected_keys = {
        "dimension",
        "code",
        "finding_kind",
        "description",
        "evidence_refs",
        "affected_action_ids",
        "affected_route_ids",
        "required_information",
    }
    finding_kinds = {"ISSUE", "EVIDENCE_GAP", "ROUTE_ISSUE", "CONFIRMATION", "BLOCKER"}
    for raw in raw_findings:
        if not isinstance(raw, Mapping) or set(raw) != expected_keys:
            raise ValueError("Review inspector finding keys do not match contract")
        item = dict(raw)
        if item["dimension"] != expected_dimension:
            raise ValueError("Review inspector finding dimension is invalid")
        if not isinstance(item["finding_kind"], str) or item["finding_kind"] not in finding_kinds:
            raise ValueError("Review inspector finding_kind is invalid")
        for key in ("code", "description"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"Review inspector {key} is required")
        for key in (
            "evidence_refs",
            "affected_action_ids",
            "affected_route_ids",
            "required_information",
        ):
            field = item[key]
            if not isinstance(field, list) or not all(
                isinstance(entry, str) and entry for entry in field
            ):
                raise ValueError(f"Review inspector {key} must contain strings")
        findings.append(cast(ReviewInspectorFindingV1, item))
    return {
        "schema_version": 1,
        "dimension": expected_dimension,
        "findings": findings,
    }


__all__ = [
    "AtomicReviewFindingV1",
    "RecheckAffectedDimensionsResultV1",
    "ReviewDimension",
    "ReviewDimensionIdV1",
    "ReviewFindingKindV1",
    "ReviewInspectorFindingV1",
    "ReviewInspectorResultV1",
    "ReviewSemanticInvoker",
    "review_inspector_output_schema",
    "validate_review_inspector_result",
]
