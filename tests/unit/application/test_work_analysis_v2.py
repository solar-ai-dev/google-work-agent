from __future__ import annotations

import pytest

from google_work_agent.application.workflows.work_analysis_v2 import (
    WorkAnalysisV2ValidationError,
    materialize_complete_work_analysis_result_v2,
    validate_work_analysis_candidate_v2,
)


def _candidate(*, relation_type: str = "DEPENDS_ON", disposition: str = "COMPLETE"):
    return {
        "schema_version": 2,
        "work_facts": [
            {
                "fact_id": "fact-1",
                "fact_type": "TASK",
                "value": "submit report",
                "evidence_refs": ["ev-1"],
            }
        ],
        "relation_candidates": [
            {
                "relation_type": relation_type,
                "left_ref": "fact-1",
                "right_ref": "resource-1",
                "evidence_refs": ["ev-1"],
            }
        ],
        "ambiguities": [],
        "risks": [],
        "evidence_refs": ["ev-1"],
        "disposition": disposition,
    }


def _meta():
    return {
        "artifact_id": "analysis-1",
        "revision": 1,
        "based_on": [
            {"artifact_id": "retrieval-1", "revision": 1},
        ],
    }


def test_candidate_rejects_nested_evidence_not_declared_at_top_level() -> None:
    candidate = _candidate()
    candidate["evidence_refs"] = []

    with pytest.raises(WorkAnalysisV2ValidationError, match="top-level evidence_refs"):
        validate_work_analysis_candidate_v2(candidate, allowed_evidence_refs={"ev-1"})


def test_complete_non_guarded_relation_materializes_without_policy_authority() -> None:
    candidate = validate_work_analysis_candidate_v2(
        _candidate(), allowed_evidence_refs={"ev-1"}
    )

    result = materialize_complete_work_analysis_result_v2(
        candidate,
        meta=_meta(),
        allowed_evidence_refs={"ev-1"},
    )

    assert result["schema_version"] == 2
    assert result["relations"] == [
        {
            "relation_type": "DEPENDS_ON",
            "left_ref": "fact-1",
            "right_ref": "resource-1",
            "evidence_refs": ["ev-1"],
            "validator_codes": [],
        }
    ]
    assert result["action_necessity"] == "REQUIRED"


@pytest.mark.parametrize("relation_type", ["DUPLICATES", "CONFLICTS_WITH"])
def test_guarded_relation_fails_closed_without_deterministic_validator(
    relation_type: str,
) -> None:
    candidate = validate_work_analysis_candidate_v2(
        _candidate(relation_type=relation_type), allowed_evidence_refs={"ev-1"}
    )

    with pytest.raises(WorkAnalysisV2ValidationError, match="deterministic relation validation"):
        materialize_complete_work_analysis_result_v2(
            candidate,
            meta=_meta(),
            allowed_evidence_refs={"ev-1"},
        )


def test_exact_duplicate_validator_can_promote_relation_and_suppress_action() -> None:
    candidate = validate_work_analysis_candidate_v2(
        _candidate(relation_type="DUPLICATES"), allowed_evidence_refs={"ev-1"}
    )

    result = materialize_complete_work_analysis_result_v2(
        candidate,
        meta=_meta(),
        allowed_evidence_refs={"ev-1"},
        relation_validator=lambda relation: {
            "accepted": True,
            "validator_codes": ["TASK_EXACT_DUPLICATE_VALIDATED"],
            "action_necessity": "NOT_REQUIRED",
        },
    )

    assert result["relations"][0]["relation_type"] == "DUPLICATES"
    assert result["relations"][0]["validator_codes"] == [
        "TASK_EXACT_DUPLICATE_VALIDATED"
    ]
    assert result["action_necessity"] == "NOT_REQUIRED"


def test_rejected_guarded_relation_is_not_promoted() -> None:
    candidate = validate_work_analysis_candidate_v2(
        _candidate(relation_type="CONFLICTS_WITH"), allowed_evidence_refs={"ev-1"}
    )

    result = materialize_complete_work_analysis_result_v2(
        candidate,
        meta=_meta(),
        allowed_evidence_refs={"ev-1"},
        relation_validator=lambda relation: {
            "accepted": False,
            "validator_codes": ["CALENDAR_CONFLICT_NOT_CONFIRMED"],
            "ambiguity": {
                "code": "CALENDAR_RELATION_UNCONFIRMED",
                "description": "candidate did not pass deterministic conflict validation",
                "evidence_refs": ["ev-1"],
            },
        },
    )

    assert result["relations"] == []
    assert result["ambiguities"][0]["code"] == "CALENDAR_RELATION_UNCONFIRMED"


def test_non_complete_candidate_cannot_become_main_state_artifact() -> None:
    candidate = validate_work_analysis_candidate_v2(
        _candidate(disposition="NEEDS_CONFIRMATION"), allowed_evidence_refs={"ev-1"}
    )

    with pytest.raises(WorkAnalysisV2ValidationError, match="only COMPLETE"):
        materialize_complete_work_analysis_result_v2(
            candidate,
            meta=_meta(),
            allowed_evidence_refs={"ev-1"},
        )
