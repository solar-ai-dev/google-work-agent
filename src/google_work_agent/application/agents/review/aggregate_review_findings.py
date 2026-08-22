"""Deterministically aggregate atomic Review findings into the canonical Review result."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    StateArtifactMetaV1,
    StateArtifactRefV1,
)

_REVIEW_DIMENSIONS = {"GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"}


def aggregate_review_findings(
    findings: Iterable[Mapping[str, object]],
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[Mapping[str, object]] = (),
) -> PlanReviewResultV2:
    """Stable-deduplicate findings and materialize the deterministic Review disposition."""
    if not artifact_id or revision < 1:
        raise ValueError("review artifact_id and positive revision are required")
    refs: list[StateArtifactRefV1] = []
    for raw in based_on:
        ref_id = raw.get("artifact_id")
        ref_revision = raw.get("revision")
        if not isinstance(ref_id, str) or not isinstance(ref_revision, int) or ref_revision < 1:
            raise ValueError("review based_on reference is invalid")
        refs.append({"artifact_id": ref_id, "revision": ref_revision})
    meta: StateArtifactMetaV1 = {
        "artifact_id": artifact_id,
        "revision": revision,
        "based_on": refs,
    }

    deduped: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for finding in findings:
        item = dict(finding)
        dimension = item.get("dimension")
        code = item.get("code")
        description = item.get("description")
        if dimension not in _REVIEW_DIMENSIONS:
            raise ValueError("review finding dimension is required")
        if not isinstance(code, str) or not code:
            raise ValueError("review finding code is required")
        if not isinstance(description, str):
            raise ValueError("review finding description must be a string")
        required = item.get("required_information", [])
        if not isinstance(required, list) or not all(isinstance(value, str) for value in required):
            raise ValueError("review finding required_information must be strings")
        identity = (
            dimension,
            code,
            description,
            item.get("action_id"),
            item.get("route_id"),
            tuple(required),
        )
        if identity not in seen:
            seen.add(identity)
            item["required_information"] = list(required)
            deduped.append(item)

    if not deduped:
        return cast(
            PlanReviewResultV2,
            {"schema_version": 2, "meta": meta, "status": "PASS", "summary": "Review passed."},
        )

    evidence_gaps = [item for item in deduped if item.get("required_information")]
    if evidence_gaps:
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
                    for item in evidence_gaps
                ],
            },
        )

    route_findings = [
        item
        for item in deduped
        if isinstance(item.get("route_id"), str) and not isinstance(item.get("action_id"), str)
    ]
    if route_findings and len(route_findings) == len(deduped):
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
                        "route_id": item["route_id"],
                    }
                    for item in route_findings
                ],
            },
        )

    return cast(
        PlanReviewResultV2,
        {
            "schema_version": 2,
            "meta": meta,
            "status": "REVISE",
            "issues": [
                {
                    "dimension": item["dimension"],
                    "code": item["code"],
                    "description": item["description"],
                    "action_id": item.get("action_id")
                    if isinstance(item.get("action_id"), str)
                    else None,
                    "route_id": item.get("route_id")
                    if isinstance(item.get("route_id"), str)
                    else None,
                }
                for item in deduped
            ],
        },
    )
