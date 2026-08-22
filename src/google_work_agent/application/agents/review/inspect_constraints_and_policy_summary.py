"""Run the CONSTRAINTS_POLICY atomic Review inspection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.review.contracts.review_findings import (
    AtomicReviewFindingV1,
    ReviewSemanticInvoker,
)

PROMPT_ID = "review.inspect_constraints_and_policy_summary"


def inspect_constraints_and_policy_summary(
    *,
    request_intent: Mapping[str, object],
    tool_route_plan: Mapping[str, object],
    planning_result: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    invoke: ReviewSemanticInvoker,
    work_analysis: Mapping[str, object] | None = None,
    policy_summary: Mapping[str, object] | None = None,
) -> tuple[AtomicReviewFindingV1, ...]:
    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "tool_route_plan": dict(tool_route_plan),
        "planning_result": dict(planning_result),
        "evidence": [dict(item) for item in evidence],
        "work_analysis": dict(work_analysis) if work_analysis is not None else None,
        "policy_summary": dict(policy_summary) if policy_summary is not None else None,
    }
    raw = invoke(PROMPT_ID, prompt_input)
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Review inspection requires findings list")
    result: list[AtomicReviewFindingV1] = []
    for item in findings:
        if not isinstance(item, Mapping):
            raise ValueError("Review finding must be an object")
        code = item.get("code")
        description = item.get("description")
        if not isinstance(code, str) or not code or not isinstance(description, str):
            raise ValueError("Review finding code/description are required")
        required = item.get("required_information", [])
        if not isinstance(required, list) or not all(isinstance(value, str) for value in required):
            raise ValueError("required_information must be strings")
        result.append({
            "dimension": "CONSTRAINTS_POLICY",
            "code": code,
            "description": description,
            "action_id": item.get("action_id") if isinstance(item.get("action_id"), str) else None,
            "route_id": item.get("route_id") if isinstance(item.get("route_id"), str) else None,
            "required_information": list(required),
        })
    return tuple(result)
