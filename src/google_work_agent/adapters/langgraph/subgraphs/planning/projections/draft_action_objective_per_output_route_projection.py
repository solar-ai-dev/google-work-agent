"""Exact input projection for Planning ACTION objective drafting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict


class DraftActionObjectiveInputV1(TypedDict):
    user_request: str
    request_intent: dict[str, object]
    output_routes: list[dict[str, object]]
    evidence: list[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]


def project_draft_action_objective_per_output_route_input(
    state: Mapping[str, object],
) -> DraftActionObjectiveInputV1:
    required = ("user_request", "request_intent", "output_plan")
    if any(key not in state for key in required):
        raise ValueError("objective projection requires request, intent, and output_plan")
    user_request, request_intent, output_plan = (state[key] for key in required)
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("user_request is required")
    if not isinstance(request_intent, Mapping) or not isinstance(output_plan, Mapping):
        raise ValueError("request_intent and output_plan must be objects")
    routes = output_plan.get("output_routes")
    if not isinstance(routes, Sequence) or isinstance(routes, (str, bytes)):
        raise ValueError("ACTION output_plan.output_routes is required")
    work_analysis = state.get("work_analysis")
    evidence = state.get("evidence", ())
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        raise ValueError("work_analysis must be an object")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    output_routes = [dict(item) for item in routes if isinstance(item, Mapping)]
    if len(output_routes) != len(routes):
        raise ValueError("output routes must be objects")
    result: DraftActionObjectiveInputV1 = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "output_routes": output_routes,
        "evidence": [dict(item) for item in evidence if isinstance(item, Mapping)],
    }
    if work_analysis is not None:
        result["work_analysis"] = dict(work_analysis)
    return result


__all__ = [
    "DraftActionObjectiveInputV1",
    "project_draft_action_objective_per_output_route_input",
]
