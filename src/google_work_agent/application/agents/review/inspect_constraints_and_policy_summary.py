"""Inspect user constraints against a supplied bounded policy summary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.review.contracts.exact_calendar_create_plan import (
    is_exact_calendar_create_plan,
)
from google_work_agent.application.agents.review.contracts.exact_task_create_plan import (
    is_exact_task_create_plan,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewInspectorResultV1,
    ReviewSemanticInvoker,
    review_inspector_output_schema,
    validate_review_inspector_result,
)

PROMPT_ID = "review.inspect_constraints_and_policy_summary"
DIMENSION: ReviewDimensionIdV1 = "review.inspect_constraints_and_policy_summary"
REVIEW_INSPECT_CONSTRAINTS_AND_POLICY_SUMMARY_OUTPUT_SCHEMA = review_inspector_output_schema(
    DIMENSION
)


def inspect_constraints_and_policy_summary(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    policy_summary: Mapping[str, object],
    invoke: ReviewSemanticInvoker,
    work_analysis: Mapping[str, object] | None = None,
    evidence: Sequence[Mapping[str, object]] = (),
    confirmation_response: Mapping[str, object] | None = None,
) -> ReviewInspectorResultV1:
    constraints = request_intent.get("constraints")
    if (
        confirmation_response is None
        and not policy_summary
        and (
            is_exact_calendar_create_plan(
                request_intent=request_intent,
                planning_result=planning_result,
            )
            or is_exact_task_create_plan(
                request_intent=request_intent,
                planning_result=planning_result,
                work_analysis=work_analysis,
            )
        )
    ):
        return {"schema_version": 1, "dimension": DIMENSION, "findings": []}
    if constraints == [] and not policy_summary and confirmation_response is None:
        # This inspector may report only supplied user-constraint or policy
        # contradictions. With both bounded inputs explicitly empty there is
        # no grounded finding an LLM is allowed to invent.
        return {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        }
    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "policy_summary": dict(policy_summary),
    }
    if work_analysis is not None:
        prompt_input["work_analysis"] = dict(work_analysis)
    if evidence:
        prompt_input["evidence"] = [dict(item) for item in evidence]
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    return validate_review_inspector_result(
        invoke(PROMPT_ID, prompt_input), expected_dimension=DIMENSION
    )


__all__ = [
    "REVIEW_INSPECT_CONSTRAINTS_AND_POLICY_SUMMARY_OUTPUT_SCHEMA",
    "inspect_constraints_and_policy_summary",
]
