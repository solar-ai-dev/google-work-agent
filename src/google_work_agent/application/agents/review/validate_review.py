"""Validate the discriminated Review result contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)

_VARIANTS = {
    "PASS": {"schema_version", "meta", "status", "summary"},
    "REVISE": {"schema_version", "meta", "status", "issues"},
    "RETRIEVE_MORE": {"schema_version", "meta", "status", "evidence_gaps"},
    "ROUTE_RECONSIDERATION": {"schema_version", "meta", "status", "route_issues"},
    "CONFIRM": {"schema_version", "meta", "status", "confirmation"},
    "BLOCK": {"schema_version", "meta", "status", "blockers"},
}


def validate_review(value: object) -> PlanReviewResultV2:
    if not isinstance(value, Mapping):
        raise ValueError("PlanReviewResultV2 must be an object")
    root = dict(value)
    if root.get("schema_version") != 2:
        raise ValueError("PlanReviewResultV2.schema_version must be 2")
    status = root.get("status")
    if not isinstance(status, str) or status not in _VARIANTS:
        raise ValueError("invalid Review status")
    if set(root) != _VARIANTS[status]:
        raise ValueError(f"{status} Review keys do not match contract")
    if status == "PASS" and not isinstance(root["summary"], str):
        raise ValueError("PASS summary must be a string")
    if status == "REVISE" and not _nonempty_object_list(root["issues"]):
        raise ValueError("REVISE requires issues")
    if status == "RETRIEVE_MORE" and not _nonempty_object_list(root["evidence_gaps"]):
        raise ValueError("RETRIEVE_MORE requires evidence gaps")
    if status == "ROUTE_RECONSIDERATION" and not _nonempty_object_list(root["route_issues"]):
        raise ValueError("ROUTE_RECONSIDERATION requires route issues")
    if status == "CONFIRM" and not isinstance(root["confirmation"], Mapping):
        raise ValueError("CONFIRM requires confirmation")
    if status == "BLOCK" and not _nonempty_object_list(root["blockers"]):
        raise ValueError("BLOCK requires blockers")
    return cast(PlanReviewResultV2, root)


def _nonempty_object_list(value: object) -> bool:
    return (
        isinstance(value, list) and bool(value) and all(isinstance(item, Mapping) for item in value)
    )
