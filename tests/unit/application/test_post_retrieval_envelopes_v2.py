from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PostRetrievalEnvelopeV2Error,
    validate_planning_return_v2,
    validate_review_return_v2,
    validate_work_analysis_return_v2,
)


def _meta(name: str):
    return {"artifact_id": name, "revision": 1, "based_on": []}


def test_analysis_complete_requires_official_artifact_and_no_signal() -> None:
    result = {
        "schema_version": 2,
        "meta": _meta("analysis-1"),
        "work_facts": [],
        "relations": [],
        "ambiguities": [],
        "risks": [],
        "evidence_refs": [],
        "policy_confirmation_receipt_refs": [],
        "action_necessity": "REQUIRED",
    }
    envelope = validate_work_analysis_return_v2(
        {"disposition": "COMPLETE", "typed_result": result, "workflow_signal": None}
    )
    assert envelope["typed_result"] == result


def test_analysis_needs_confirmation_cannot_promote_candidate() -> None:
    with pytest.raises(PostRetrievalEnvelopeV2Error, match="must not promote"):
        validate_work_analysis_return_v2(
            {
                "disposition": "NEEDS_CONFIRMATION",
                "typed_result": {"schema_version": 2},
                "workflow_signal": {
                    "kind": "CONFIRMATION_REQUIRED",
                    "interrupt_id": "i1",
                    "owner_subgraph": "WORK_ANALYSIS",
                    "resume_target": {
                        "subgraph_id": "WORK_ANALYSIS",
                        "node_id": "finalize",
                        "graph_version": "v1",
                    },
                    "question": "which?",
                    "options": [],
                },
            }
        )


def test_planning_answer_only_requires_answer_draft_v2() -> None:
    envelope = validate_planning_return_v2(
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
    assert envelope["disposition"] == "ANSWER_ONLY"


def test_review_retrieve_more_preserves_review_artifact_and_signal() -> None:
    envelope = validate_review_return_v2(
        {
            "disposition": "RETRIEVE_MORE",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("review-1"),
                "status": "RETRIEVE_MORE",
                "evidence_gaps": [
                    {
                        "code": "MISSING_RECIPIENT",
                        "description": "recipient missing",
                        "required_information": ["recipient email"],
                    }
                ],
            },
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
    assert envelope["typed_result"]["status"] == "RETRIEVE_MORE"


def test_review_pass_rejects_control_signal() -> None:
    with pytest.raises(PostRetrievalEnvelopeV2Error, match="must not carry"):
        validate_review_return_v2(
            {
                "disposition": "PASS",
                "typed_result": {
                    "schema_version": 2,
                    "meta": _meta("review-1"),
                    "status": "PASS",
                    "summary": "ok",
                },
                "workflow_signal": {"kind": "BLOCKED", "reason_codes": ["x"]},
            }
        )
