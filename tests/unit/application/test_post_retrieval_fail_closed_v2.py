from __future__ import annotations

from google_work_agent.application.workflows.contracts import build_default_run_budget
from google_work_agent.application.workflows.post_retrieval_supervisor_v2 import (
    route_planning_return_v2,
    route_review_return_v2,
    route_work_analysis_return_v2,
)


def _meta(name: str) -> dict[str, object]:
    return {"artifact_id": name, "revision": 1, "based_on": []}


def _answer() -> dict[str, object]:
    return {
        "schema_version": 2,
        "meta": _meta("answer-1"),
        "answer": "done",
        "evidence_refs": [],
    }


def test_legacy_status_only_work_analysis_does_not_route() -> None:
    decision = route_work_analysis_return_v2({"status": "COMPLETE", "result": {}})
    assert decision["target"] == "RECOVERY"
    assert decision["reason_code"] == "CONTRACT_VIOLATION"


def test_unknown_planning_disposition_fails_closed() -> None:
    decision = route_planning_return_v2(
        {"disposition": "MAYBE", "typed_result": None, "workflow_signal": None}
    )
    assert decision["target"] == "RECOVERY"
    assert decision["reason_code"] == "CONTRACT_VIOLATION"


def test_review_pass_on_answer_is_contract_violation_not_finalize() -> None:
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
        planning_result=_answer(),
        retry_budget=build_default_run_budget(),
    )
    assert decision["target"] == "RECOVERY"
    assert decision["reason_code"] == "CONTRACT_VIOLATION"
