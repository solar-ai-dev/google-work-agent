"""Deterministically aggregate validated Review findings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewInspectorFindingV1,
)

_DIMENSIONS: tuple[ReviewDimensionIdV1, ...] = (
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
)
_DIMENSION_SET = set(_DIMENSIONS)
# Safety/stop requirements dominate redirection, acquisition, and revision.
_PRECEDENCE = ("BLOCKER", "CONFIRMATION", "ROUTE_ISSUE", "EVIDENCE_GAP", "ISSUE")


def aggregate_review_findings(
    findings: Iterable[Mapping[str, object]],
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[Mapping[str, object]] = (),
) -> PlanReviewResultV2:
    """Apply the closed precedence without creating semantic findings."""
    meta = _meta(artifact_id=artifact_id, revision=revision, based_on=based_on)
    validated = _validated_findings(findings)
    if not validated:
        return cast(
            PlanReviewResultV2,
            {"schema_version": 2, "meta": meta, "status": "PASS", "summary": "Review passed."},
        )

    selected_kind = next(
        kind for kind in _PRECEDENCE if any(item["finding_kind"] == kind for item in validated)
    )
    selected = [item for item in validated if item["finding_kind"] == selected_kind]

    if selected_kind == "BLOCKER":
        return cast(
            PlanReviewResultV2,
            {
                "schema_version": 2,
                "meta": meta,
                "status": "BLOCK",
                "blockers": [
                    {
                        "code": item["code"],
                        "description": item["description"],
                        "affected_action_ids": list(item["affected_action_ids"]),
                    }
                    for item in selected
                ],
            },
        )
    if selected_kind == "CONFIRMATION":
        finding = selected[0]
        return cast(
            PlanReviewResultV2,
            {
                "schema_version": 2,
                "meta": meta,
                "status": "CONFIRM",
                "confirmation": {
                    "question": finding["description"],
                    "options": list(finding["required_information"]),
                },
            },
        )
    if selected_kind == "ROUTE_ISSUE":
        return cast(
            PlanReviewResultV2,
            {
                "schema_version": 2,
                "meta": meta,
                "status": "ROUTE_RECONSIDERATION",
                "route_issues": [
                    {
                        "code": item["code"],
                        "description": item["description"],
                        "affected_route_ids": list(item["affected_route_ids"]),
                    }
                    for item in selected
                ],
            },
        )
    if selected_kind == "EVIDENCE_GAP":
        return cast(
            PlanReviewResultV2,
            {
                "schema_version": 2,
                "meta": meta,
                "status": "RETRIEVE_MORE",
                "evidence_gaps": [
                    {
                        "code": item["code"],
                        "description": item["description"],
                        "required_information": list(item["required_information"]),
                    }
                    for item in selected
                ],
            },
        )

    return cast(
        PlanReviewResultV2,
        {
            "schema_version": 2,
            "meta": meta,
            "status": "REVISE",
            "issues": _merge_issues(selected),
        },
    )


def _meta(
    *, artifact_id: str, revision: int, based_on: Iterable[Mapping[str, object]]
) -> StateArtifactMetaV1:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError("review artifact_id is required")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("review revision must be positive")
    refs: list[StateArtifactRefV1] = []
    seen: set[tuple[str, int]] = set()
    for raw in based_on:
        if set(raw) != {"artifact_id", "revision"}:
            raise ValueError("review based_on reference keys are invalid")
        ref_id = raw.get("artifact_id")
        ref_revision = raw.get("revision")
        if not isinstance(ref_id, str) or not ref_id:
            raise ValueError("review based_on artifact_id is required")
        if not isinstance(ref_revision, int) or isinstance(ref_revision, bool) or ref_revision < 1:
            raise ValueError("review based_on revision must be positive")
        identity = (ref_id, ref_revision)
        if identity not in seen:
            seen.add(identity)
            refs.append({"artifact_id": ref_id, "revision": ref_revision})
    return {"artifact_id": artifact_id, "revision": revision, "based_on": refs}


def _validated_findings(
    findings: Iterable[Mapping[str, object]],
) -> list[ReviewInspectorFindingV1]:
    result: list[ReviewInspectorFindingV1] = []
    seen: set[tuple[object, ...]] = set()
    expected = {
        "dimension",
        "code",
        "finding_kind",
        "description",
        "evidence_refs",
        "affected_action_ids",
        "affected_route_ids",
        "required_information",
    }
    for raw in findings:
        if set(raw) != expected:
            raise ValueError("Review finding keys do not match contract")
        item = dict(raw)
        if item["dimension"] not in _DIMENSION_SET:
            raise ValueError("Review finding dimension is invalid")
        if item["finding_kind"] not in _PRECEDENCE:
            raise ValueError("Review finding kind is invalid")
        for key in ("code", "description"):
            if not isinstance(item[key], str) or not item[key]:
                raise ValueError(f"Review finding {key} is required")
        for key in (
            "evidence_refs",
            "affected_action_ids",
            "affected_route_ids",
            "required_information",
        ):
            value = item[key]
            if not isinstance(value, list) or not all(
                isinstance(entry, str) and entry for entry in value
            ):
                raise ValueError(f"Review finding {key} must contain strings")
            item[key] = _ordered_unique(value)
        identity = (
            item["dimension"],
            item["code"],
            item["finding_kind"],
            item["description"],
            tuple(cast(list[str], item["evidence_refs"])),
            tuple(cast(list[str], item["affected_action_ids"])),
            tuple(cast(list[str], item["affected_route_ids"])),
            tuple(cast(list[str], item["required_information"])),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(cast(ReviewInspectorFindingV1, item))
    return result


def _merge_issues(findings: list[ReviewInspectorFindingV1]) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for finding in findings:
        key = (finding["code"], finding["description"])
        issue = merged.setdefault(
            key,
            {
                "code": finding["code"],
                "description": finding["description"],
                "affected_dimensions": [],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "evidence_refs": [],
            },
        )
        for field, values in (
            ("affected_dimensions", [finding["dimension"]]),
            ("affected_action_ids", finding["affected_action_ids"]),
            ("affected_route_ids", finding["affected_route_ids"]),
            ("evidence_refs", finding["evidence_refs"]),
        ):
            issue[field] = _ordered_unique([*cast(list[str], issue[field]), *values])
    return list(merged.values())


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = ["aggregate_review_findings"]
