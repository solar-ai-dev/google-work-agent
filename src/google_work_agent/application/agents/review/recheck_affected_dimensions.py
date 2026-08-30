"""Product-LLM recheck limited by a deterministic affected-dimension selector."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.review.contracts.review_findings import (
    RecheckAffectedDimensionsResultV1,
    ReviewDimensionIdV1,
    ReviewInspectorFindingV1,
    ReviewSemanticInvoker,
)

PROMPT_ID = "review.recheck_affected_dimensions"
_DIMENSIONS: tuple[ReviewDimensionIdV1, ...] = (
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
)
_DIMENSION_SET = set(_DIMENSIONS)
_FINDING_KINDS = {"ISSUE", "EVIDENCE_GAP", "ROUTE_ISSUE", "CONFIRMATION", "BLOCKER"}


def recheck_affected_dimensions(
    *,
    affected_dimensions: Iterable[ReviewDimensionIdV1],
    affected_action_ids: Iterable[str] = (),
    affected_route_ids: Iterable[str] = (),
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    invoke: ReviewSemanticInvoker,
    tool_route_plan: Mapping[str, object] | None = None,
    work_analysis: Mapping[str, object] | None = None,
    evidence: Sequence[Mapping[str, object]] = (),
    policy_summary: Mapping[str, object] | None = None,
    confirmation_response: Mapping[str, object] | None = None,
) -> RecheckAffectedDimensionsResultV1:
    """Return fresh replacement findings for exactly the supplied closed dimension set."""
    dimensions = _normalize_dimensions(affected_dimensions)
    if not dimensions:
        raise ValueError("Review recheck requires affected_dimensions")
    prompt_input: dict[str, object] = {
        "affected_dimensions": list(dimensions),
        "affected_action_ids": _stable_ids(affected_action_ids, "affected_action_ids"),
        "affected_route_ids": _stable_ids(affected_route_ids, "affected_route_ids"),
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "evidence": [dict(item) for item in evidence],
    }
    for key, value in (
        ("tool_route_plan", tool_route_plan),
        ("work_analysis", work_analysis),
        ("policy_summary", policy_summary),
        ("confirmation_response", confirmation_response),
    ):
        if value is not None:
            prompt_input[key] = dict(value)

    raw = invoke(PROMPT_ID, prompt_input)
    if set(raw) != {"schema_version", "affected_dimensions", "findings"}:
        raise ValueError("Review recheck result keys do not match contract")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise ValueError("Review recheck schema_version must be 1")
    returned_dimensions = _normalize_dimensions(_sequence(raw.get("affected_dimensions")))
    if returned_dimensions != dimensions:
        raise ValueError("Review recheck cannot broaden or narrow affected_dimensions")
    findings = tuple(_validate_findings(_sequence(raw.get("findings")), dimensions))
    return {"schema_version": 1, "affected_dimensions": dimensions, "findings": findings}


def _validate_findings(
    values: Sequence[object], dimensions: tuple[ReviewDimensionIdV1, ...]
) -> list[ReviewInspectorFindingV1]:
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
    allowed = set(dimensions)
    result: list[ReviewInspectorFindingV1] = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("Review recheck finding keys do not match contract")
        item = dict(value)
        if item["dimension"] not in allowed:
            raise ValueError("Review recheck returned an unaffected dimension")
        if item["finding_kind"] not in _FINDING_KINDS:
            raise ValueError("Review recheck finding_kind is invalid")
        for key in ("code", "description"):
            if not isinstance(item[key], str) or not item[key]:
                raise ValueError(f"Review recheck {key} is required")
        for key in (
            "evidence_refs",
            "affected_action_ids",
            "affected_route_ids",
            "required_information",
        ):
            item[key] = _stable_ids(_sequence(item[key]), key)
        result.append(cast(ReviewInspectorFindingV1, item))
    return result


def _normalize_dimensions(values: Iterable[object]) -> tuple[ReviewDimensionIdV1, ...]:
    requested = set(values)
    if requested - _DIMENSION_SET:
        raise ValueError("invalid Review affected dimension")
    return tuple(dimension for dimension in _DIMENSIONS if dimension in requested)


def _stable_ids(values: Iterable[object], label: str) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must contain nonempty strings")
        if value not in result:
            result.append(value)
    return result


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Review recheck arrays are required")
    return value


__all__ = ["PROMPT_ID", "recheck_affected_dimensions"]
