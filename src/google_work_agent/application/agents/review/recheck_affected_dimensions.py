"""Bounded semantic Review recheck for dimensions affected by a revision."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from google_work_agent.application.agents.review.contracts.review_findings import (
    AtomicReviewFindingV1,
    RecheckAffectedDimensionsResultV1,
    ReviewDimension,
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)

PROMPT_ID = "review.recheck_affected_dimensions"
_REVIEW_DIMENSIONS: tuple[ReviewDimension, ...] = (
    "GOAL_EVIDENCE",
    "ACTION_SCOPE_ROUTE",
    "CONSTRAINTS_POLICY",
)
_REVIEW_DIMENSION_SET = set(_REVIEW_DIMENSIONS)


def recheck_affected_dimensions(
    findings: Iterable[Mapping[str, object]],
    *,
    affected_dimensions: Iterable[ReviewDimension] = (),
    affected_action_ids: Iterable[str] = (),
    affected_route_ids: Iterable[str] = (),
    request_intent: Mapping[str, object],
    tool_route_plan: Mapping[str, object],
    planning_result: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    invoke: ReviewSemanticInvoker,
    work_analysis: Mapping[str, object] | None = None,
    policy_summary: Mapping[str, object] | None = None,
) -> RecheckAffectedDimensionsResultV1:
    """Re-run exactly the canonical union of explicitly and identity-affected dimensions."""
    prior_findings = tuple(dict(item) for item in findings)
    action_ids = set(affected_action_ids)
    route_ids = set(affected_route_ids)
    explicit_dimensions = _normalize_dimensions(affected_dimensions)
    canonical_dimensions: set[ReviewDimension] = set(explicit_dimensions)

    for finding in prior_findings:
        dimension = finding.get("dimension")
        if dimension not in _REVIEW_DIMENSION_SET:
            continue
        action_id = finding.get("action_id")
        route_id = finding.get("route_id")
        if (
            (isinstance(action_id, str) and action_id in action_ids)
            or (isinstance(route_id, str) and route_id in route_ids)
        ):
            canonical_dimensions.add(dimension)  # type: ignore[arg-type]

    if not canonical_dimensions:
        return {"affected_dimensions": (), "findings": ()}

    ordered_dimensions = tuple(
        dimension for dimension in _REVIEW_DIMENSIONS if dimension in canonical_dimensions
    )
    recheck_decision = invoke(
        PROMPT_ID,
        {
            "base_projection": {"findings": prior_findings},
            "candidate_output": {"planning_result": dict(planning_result)},
            "failure_record": {
                "affected_dimensions": list(explicit_dimensions),
                "affected_action_ids": sorted(action_ids),
                "affected_route_ids": sorted(route_ids),
                "candidate_dimensions": list(ordered_dimensions),
            },
        },
    )
    selected = recheck_decision.get("affected_dimensions")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise ValueError("recheck_affected_dimensions requires affected_dimensions")
    selected_dimensions = _normalize_dimensions(selected)
    if set(selected_dimensions) != canonical_dimensions:
        raise ValueError("recheck affected_dimensions must match the canonical affected set")

    common = {
        "request_intent": request_intent,
        "tool_route_plan": tool_route_plan,
        "planning_result": planning_result,
        "work_analysis": work_analysis,
        "evidence": evidence,
        "policy_summary": policy_summary,
        "invoke": invoke,
    }
    fresh: list[AtomicReviewFindingV1] = []
    if "GOAL_EVIDENCE" in canonical_dimensions:
        fresh.extend(inspect_goal_and_evidence(**common))
    if "ACTION_SCOPE_ROUTE" in canonical_dimensions:
        fresh.extend(inspect_action_scope_and_route(**common))
    if "CONSTRAINTS_POLICY" in canonical_dimensions:
        fresh.extend(inspect_constraints_and_policy_summary(**common))
    return {"affected_dimensions": ordered_dimensions, "findings": tuple(fresh)}


def _normalize_dimensions(dimensions: Iterable[object]) -> tuple[ReviewDimension, ...]:
    requested = set(dimensions)
    invalid = requested - _REVIEW_DIMENSION_SET
    if invalid:
        raise ValueError("invalid Review affected dimension")
    return tuple(dimension for dimension in _REVIEW_DIMENSIONS if dimension in requested)
