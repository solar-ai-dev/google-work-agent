from __future__ import annotations

from google_work_agent.application.workflows.contracts import build_default_run_budget
from google_work_agent.application.workflows.post_retrieval_supervisor_v2 import (
    route_planning_return_v2,
    route_review_return_v2,
    route_work_analysis_return_v2,
)


def _meta(name: str):
    return {"artifact_id": name, "revision": 1, "based_on": []}


def _plan():
    return {
        "schema_version": 2,
        "meta": _meta("plan-1"),
        "actions": [
            {
                "action_id": "a1",
                "route_id": "r1",
                "tool_id": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {"task_list_id": "l1", "payload": {"title": "x"}},
                "evidence_refs": ["ev-1"],
                "depends_on_action_ids": [],
            }
        ],
    }


def test_planning_answer_only_skips_review() -> None:
    decision = route_planning_return_v2(
        {
            "disposition": "ANSWER_ONLY",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("answer-1"),
                "answer": "done",
                "evidence_refs": [],
            },
            "workflow_signal": None,
        }
    )
    assert decision["target"] == "RESPONSE_SYNTHESIS"


def test_analysis_needs_more_data_uses_signal_not_result_internals() -> None:
    decision = route_work_analysis_return_v2(
        {
            "disposition": "NEEDS_MORE_DATA",
            "typed_result": None,
            "workflow_signal": {
                "kind": "RETRIEVAL_REQUIRED",
                "reason_codes": ["MISSING_RECIPIENT"],
                "needs": [
                    {
                        "required_information": "recipient email",
                        "reason_codes": ["MISSING_RECIPIENT"],
                    }
                ],
            },
        }
    )
    assert decision["target"] == "RETRIEVAL"
    assert decision["reason_code"] == "MISSING_RECIPIENT"


def test_review_pass_routes_action_plan_to_domain_validation() -> None:
    decision = route_review_return_v2(
        {
            "disposition": "PASS",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("review-1"),
                "status": "PASS",
                "summary": "ok",
            },
            "workflow_signal": None,
        },
        planning_result=_plan(),
        retry_budget=build_default_run_budget(),
    )
    assert decision["target"] == "DOMAIN_VALIDATION"


def test_review_revise_uses_canonical_issue_code_for_semantic_budget() -> None:
    decision = route_review_return_v2(
        {
            "disposition": "REVISE",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("review-1"),
                "status": "REVISE",
                "issues": [
                    {"code": "PLAN_WRONG_TARGET", "description": "wrong", "action_id": "a1"}
                ],
            },
            "workflow_signal": None,
        },
        planning_result=_plan(),
        retry_budget=build_default_run_budget(),
    )
    assert decision["target"] == "PLANNING"
    assert decision["revision_mode"] == "PLAN"
    assert decision["retry_budget"] is not None
