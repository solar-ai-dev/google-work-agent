"""Validate the exact discriminated PlanReviewResultV2 contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)

_DIMENSIONS = {
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
}
_VARIANTS = {
    "PASS": ("summary",),
    "REVISE": ("issues",),
    "RETRIEVE_MORE": ("evidence_gaps",),
    "ROUTE_RECONSIDERATION": ("route_issues",),
    "CONFIRM": ("confirmation",),
    "BLOCK": ("blockers",),
}


def validate_review(value: object) -> PlanReviewResultV2:
    root = _mapping(value, "PlanReviewResultV2")
    if root.get("schema_version") != 2 or isinstance(root.get("schema_version"), bool):
        raise ValueError("PlanReviewResultV2.schema_version must be 2")
    status = root.get("status")
    if not isinstance(status, str) or status not in _VARIANTS:
        raise ValueError("invalid Review status")
    expected = {"schema_version", "meta", "status", *_VARIANTS[status]}
    _exact(root, expected, f"{status} Review")
    _validate_meta(root["meta"])

    if status == "PASS":
        _string(root["summary"], "PASS summary", allow_empty=True)
    elif status == "REVISE":
        for item in _object_list(root["issues"], "REVISE issues", nonempty=True):
            _exact(
                item,
                {
                    "code",
                    "description",
                    "affected_dimensions",
                    "affected_action_ids",
                    "affected_route_ids",
                    "evidence_refs",
                },
                "ReviewIssueV1",
            )
            _code_description(item)
            dimensions = _string_list(item["affected_dimensions"], "affected_dimensions", True)
            if any(dimension not in _DIMENSIONS for dimension in dimensions):
                raise ValueError("ReviewIssueV1 affected_dimensions is invalid")
            _string_list(item["affected_action_ids"], "affected_action_ids")
            _string_list(item["affected_route_ids"], "affected_route_ids")
            _string_list(item["evidence_refs"], "evidence_refs")
    elif status == "RETRIEVE_MORE":
        for item in _object_list(root["evidence_gaps"], "evidence_gaps", nonempty=True):
            _exact(item, {"code", "description", "required_information"}, "EvidenceGapV1")
            _code_description(item)
            _string_list(item["required_information"], "required_information", True)
    elif status == "ROUTE_RECONSIDERATION":
        for item in _object_list(root["route_issues"], "route_issues", nonempty=True):
            _exact(item, {"code", "description", "affected_route_ids"}, "RouteIssueV1")
            _code_description(item)
            _string_list(item["affected_route_ids"], "affected_route_ids")
    elif status == "CONFIRM":
        confirmation = _mapping(root["confirmation"], "ReviewConfirmationV1")
        _exact(confirmation, {"question", "options"}, "ReviewConfirmationV1")
        _string(confirmation["question"], "confirmation question")
        _string_list(confirmation["options"], "confirmation options")
    else:
        for item in _object_list(root["blockers"], "blockers", nonempty=True):
            _exact(item, {"code", "description", "affected_action_ids"}, "ReviewBlockerV1")
            _code_description(item)
            _string_list(item["affected_action_ids"], "affected_action_ids")
    return cast(PlanReviewResultV2, root)


def _validate_meta(value: object) -> None:
    meta = _mapping(value, "Review meta")
    _exact(meta, {"artifact_id", "revision", "based_on"}, "Review meta")
    _string(meta["artifact_id"], "Review meta artifact_id")
    revision = meta["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("Review meta revision must be positive")
    for ref in _object_list(meta["based_on"], "Review meta based_on"):
        _exact(ref, {"artifact_id", "revision"}, "StateArtifactRefV1")
        _string(ref["artifact_id"], "StateArtifactRefV1 artifact_id")
        ref_revision = ref["revision"]
        if not isinstance(ref_revision, int) or isinstance(ref_revision, bool) or ref_revision < 1:
            raise ValueError("StateArtifactRefV1 revision must be positive")


def _code_description(item: Mapping[str, object]) -> None:
    _string(item["code"], "Review item code")
    _string(item["description"], "Review item description")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _object_list(value: object, label: str, nonempty: bool = False) -> list[dict[str, object]]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} must be a{' nonempty' if nonempty else 'n'} array")
    return [_mapping(item, label) for item in value]


def _string_list(value: object, label: str, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} must be a string array")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must contain nonempty strings")
    return value


def _string(value: object, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{label} must be a string")
    return value


def _exact(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys do not match contract")


__all__ = ["validate_review"]
