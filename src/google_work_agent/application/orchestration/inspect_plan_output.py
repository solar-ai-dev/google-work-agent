"""Canonical Review V2 candidate validation and State Artifact materialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.orchestration.handoff_contracts import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.application.orchestration.state_artifacts import (
    PlanReviewResultV2,
    ReviewBlockV2,
    ReviewBlockerV1,
    ReviewConfirmV2,
    ReviewConfirmationV1,
    ReviewEvidenceGapV1,
    ReviewIssueV1,
    ReviewPassV2,
    ReviewRetrieveMoreV2,
    ReviewReviseV2,
    ReviewRouteIssueV1,
    ReviewRouteReconsiderationV2,
)
from google_work_agent.ports import OutputSchemaDefinition

ReviewStatusV2 = Literal[
    "PASS",
    "REVISE",
    "RETRIEVE_MORE",
    "ROUTE_RECONSIDERATION",
    "CONFIRM",
    "BLOCK",
]


class PlanReviewCandidateV2(TypedDict, total=False):
    schema_version: Required[Literal[2]]
    status: Required[ReviewStatusV2]
    summary: str
    issues: list[dict[str, object]]
    evidence_gaps: list[dict[str, object]]
    route_issues: list[dict[str, object]]
    confirmation: dict[str, object] | None
    blockers: list[dict[str, object]]


PLAN_REVIEW_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="plan-review-result-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "status"],
        "properties": {
            "schema_version": {"type": "integer", "const": 2},
            "status": {
                "type": "string",
                "enum": [
                    "PASS",
                    "REVISE",
                    "RETRIEVE_MORE",
                    "ROUTE_RECONSIDERATION",
                    "CONFIRM",
                    "BLOCK",
                ],
            },
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": {"type": "object"}},
            "evidence_gaps": {"type": "array", "items": {"type": "object"}},
            "route_issues": {"type": "array", "items": {"type": "object"}},
            "confirmation": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    },
)

_VARIANT_KEYS: dict[str, set[str]] = {
    "PASS": {"schema_version", "status", "summary"},
    "REVISE": {"schema_version", "status", "issues"},
    "RETRIEVE_MORE": {"schema_version", "status", "evidence_gaps"},
    "ROUTE_RECONSIDERATION": {"schema_version", "status", "route_issues"},
    "CONFIRM": {"schema_version", "status", "confirmation"},
    "BLOCK": {"schema_version", "status", "blockers"},
}


class ReviewV2ValidationError(ValueError):
    """Review candidate violates the canonical discriminated union."""


def validate_plan_review_candidate_v2(value: object) -> PlanReviewCandidateV2:
    root = _mapping(value, "$")
    if root.get("schema_version") != 2:
        raise ReviewV2ValidationError("$.schema_version must be 2")
    status = root.get("status")
    if not isinstance(status, str) or status not in _VARIANT_KEYS:
        raise ReviewV2ValidationError("$.status is invalid")
    expected = _VARIANT_KEYS[status]
    if set(root) != expected:
        missing = expected - set(root)
        extra = set(root) - expected
        raise ReviewV2ValidationError(
            f"{status} keys mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )

    if status == "PASS":
        _string(root["summary"], "$.summary", allow_empty=True)
    elif status == "REVISE":
        _review_issues(root["issues"])
    elif status == "RETRIEVE_MORE":
        _evidence_gaps(root["evidence_gaps"])
    elif status == "ROUTE_RECONSIDERATION":
        _route_issues(root["route_issues"])
    elif status == "CONFIRM":
        _confirmation(root["confirmation"])
    else:
        blockers = _blockers(root["blockers"])
        if not blockers:
            raise ReviewV2ValidationError("BLOCK requires at least one blocker")
    return cast(PlanReviewCandidateV2, root)


def materialize_plan_review_result_v2(
    candidate: PlanReviewCandidateV2,
    *,
    meta: StateArtifactMetaV1,
) -> PlanReviewResultV2:
    validated = validate_plan_review_candidate_v2(candidate)
    artifact_meta = _artifact_meta(meta)
    status = cast(str, validated["status"])
    base = {"schema_version": 2, "meta": artifact_meta, "status": status}
    if status == "PASS":
        return cast(ReviewPassV2, {**base, "summary": validated["summary"]})
    if status == "REVISE":
        return cast(ReviewReviseV2, {**base, "issues": _review_issues(validated["issues"])})
    if status == "RETRIEVE_MORE":
        return cast(
            ReviewRetrieveMoreV2,
            {**base, "evidence_gaps": _evidence_gaps(validated["evidence_gaps"])},
        )
    if status == "ROUTE_RECONSIDERATION":
        return cast(
            ReviewRouteReconsiderationV2,
            {**base, "route_issues": _route_issues(validated["route_issues"])},
        )
    if status == "CONFIRM":
        return cast(
            ReviewConfirmV2,
            {**base, "confirmation": _confirmation(validated["confirmation"])},
        )
    return cast(ReviewBlockV2, {**base, "blockers": _blockers(validated["blockers"])})


def _review_issues(value: object) -> list[ReviewIssueV1]:
    values = _object_list(value, "$.issues")
    result: list[ReviewIssueV1] = []
    for index, item in enumerate(values):
        path = f"$.issues[{index}]"
        _exact(item, {"code", "description", "action_id"}, path)
        action_id = item["action_id"]
        if action_id is not None and not isinstance(action_id, str):
            raise ReviewV2ValidationError(f"{path}.action_id must be string or null")
        result.append(
            {
                "code": _string(item["code"], f"{path}.code"),
                "description": _string(item["description"], f"{path}.description"),
                "action_id": cast(str | None, action_id),
            }
        )
    return result


def _evidence_gaps(value: object) -> list[ReviewEvidenceGapV1]:
    values = _object_list(value, "$.evidence_gaps")
    result: list[ReviewEvidenceGapV1] = []
    for index, item in enumerate(values):
        path = f"$.evidence_gaps[{index}]"
        _exact(item, {"code", "description", "required_information"}, path)
        result.append(
            {
                "code": _string(item["code"], f"{path}.code"),
                "description": _string(item["description"], f"{path}.description"),
                "required_information": _string_list(
                    item["required_information"], f"{path}.required_information"
                ),
            }
        )
    return result


def _route_issues(value: object) -> list[ReviewRouteIssueV1]:
    values = _object_list(value, "$.route_issues")
    result: list[ReviewRouteIssueV1] = []
    for index, item in enumerate(values):
        path = f"$.route_issues[{index}]"
        _exact(item, {"code", "description", "route_id"}, path)
        route_id = item["route_id"]
        if route_id is not None and not isinstance(route_id, str):
            raise ReviewV2ValidationError(f"{path}.route_id must be string or null")
        result.append(
            {
                "code": _string(item["code"], f"{path}.code"),
                "description": _string(item["description"], f"{path}.description"),
                "route_id": cast(str | None, route_id),
            }
        )
    return result


def _confirmation(value: object) -> ReviewConfirmationV1:
    item = _mapping(value, "$.confirmation")
    _exact(item, {"reason_code", "question", "options"}, "$.confirmation")
    return {
        "reason_code": _string(item["reason_code"], "$.confirmation.reason_code"),
        "question": _string(item["question"], "$.confirmation.question"),
        "options": _string_list(item["options"], "$.confirmation.options"),
    }


def _blockers(value: object) -> list[ReviewBlockerV1]:
    values = _object_list(value, "$.blockers")
    result: list[ReviewBlockerV1] = []
    for index, item in enumerate(values):
        path = f"$.blockers[{index}]"
        _exact(item, {"code", "description"}, path)
        result.append(
            {
                "code": _string(item["code"], f"{path}.code"),
                "description": _string(item["description"], f"{path}.description"),
            }
        )
    return result


def _artifact_meta(value: object) -> StateArtifactMetaV1:
    item = _mapping(value, "$.meta")
    _exact(item, {"artifact_id", "revision", "based_on"}, "$.meta")
    artifact_id = _string(item["artifact_id"], "$.meta.artifact_id")
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ReviewV2ValidationError("$.meta.revision must be positive")
    based_on = item["based_on"]
    if not isinstance(based_on, list):
        raise ReviewV2ValidationError("$.meta.based_on must be an array")
    refs: list[StateArtifactRefV1] = []
    for index, raw in enumerate(based_on):
        ref = _mapping(raw, f"$.meta.based_on[{index}]")
        _exact(ref, {"artifact_id", "revision"}, f"$.meta.based_on[{index}]")
        ref_id = _string(ref["artifact_id"], f"$.meta.based_on[{index}].artifact_id")
        ref_revision = ref["revision"]
        if not isinstance(ref_revision, int) or isinstance(ref_revision, bool) or ref_revision < 1:
            raise ReviewV2ValidationError(f"$.meta.based_on[{index}].revision must be positive")
        refs.append({"artifact_id": ref_id, "revision": ref_revision})
    return {"artifact_id": artifact_id, "revision": revision, "based_on": refs}


def _object_list(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReviewV2ValidationError(f"{path} must be an array")
    return [_mapping(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewV2ValidationError(f"{path} must be an array")
    return [_string(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ReviewV2ValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReviewV2ValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _string(value: object, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ReviewV2ValidationError(f"{path} must be a string")
    return value


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise ReviewV2ValidationError(f"{path} keys are invalid")


__all__ = [
    "PLAN_REVIEW_CANDIDATE_OUTPUT_SCHEMA",
    "PlanReviewCandidateV2",
    "ReviewV2ValidationError",
    "materialize_plan_review_result_v2",
    "validate_plan_review_candidate_v2",
]
