"""Exact input projection for per-route Tool argument composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast


def project_compose_arguments_per_output_route_input(
    state: Mapping[str, object],
) -> dict[str, object]:
    output_plan = state.get("output_plan")
    objectives = state.get("action_objective_candidates")
    if not isinstance(output_plan, Mapping):
        raise ValueError("output_plan is required")
    routes = _objects(output_plan.get("output_routes"), "output_routes")
    objective_items = _objects(objectives, "objectives")
    evidence = state.get("evidence", ())
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    result: dict[str, object] = {
        "output_routes": routes,
        "objectives": objective_items,
        "evidence": [dict(item) for item in evidence if isinstance(item, Mapping)],
    }
    if len(cast(list[object], result["evidence"])) != len(evidence):
        raise ValueError("evidence items must be objects")
    work_analysis = state.get("work_analysis")
    confirmation = state.get("confirmation_response")
    if work_analysis is not None:
        if not isinstance(work_analysis, Mapping):
            raise ValueError("work_analysis must be an object")
        result["work_analysis"] = dict(work_analysis)
    if confirmation is not None:
        if not isinstance(confirmation, Mapping):
            raise ValueError("confirmation_response must be an object")
        result["confirmation_response"] = dict(confirmation)
    return result


def _objects(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} items must be objects")
    return [dict(cast(Mapping[str, object], item)) for item in value]


__all__ = ["project_compose_arguments_per_output_route_input"]
