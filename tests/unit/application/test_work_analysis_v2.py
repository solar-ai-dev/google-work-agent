from __future__ import annotations

import pytest

import google_work_agent.application.workflows.work_analysis_v2 as work_analysis_v2
from google_work_agent.application.workflows.work_analysis_v2 import (
    WorkAnalysisV2ValidationError,
    materialize_complete_work_analysis_result_v2,
    validate_work_analysis_local_aggregation,
)


def _local(*, relation_type: str = "DEPENDS_ON"):
    return {
        "fact_candidates": [
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
        "relation_validation_ambiguities": [],
        "ambiguity_candidates": [],
        "evidence_refs": ["ev-1"],
    }


def _meta():
    return {
        "artifact_id": "analysis-1",
        "revision": 1,
        "based_on": [{"artifact_id": "retrieval-1", "revision": 1}],
    }


def _materialize(local, *, relation_validator=None):
    return materialize_complete_work_analysis_result_v2(
        local,
        meta=_meta(),
        allowed_evidence_refs={"ev-1"},
        validated_risks=[],
        policy_confirmation_receipt_refs=[],
        relation_validator=relation_validator,
    )


def test_local_aggregation_is_not_a_product_prompt_output_schema() -> None:
    assert not hasattr(work_analysis_v2, "WORK_ANALYSIS_CANDIDATE_OUTPUT_SCHEMA")
    assert not hasattr(work_analysis_v2, "WorkAnalysisCandidateV2")


def test_local_aggregation_rejects_nested_evidence_not_declared_at_top_level() -> None:
    local = _local()
    local["evidence_refs"] = []

    with pytest.raises(WorkAnalysisV2ValidationError, match="top-level evidence_refs"):
        validate_work_analysis_local_aggregation(local, allowed_evidence_refs={"ev-1"})


def test_complete_non_guarded_relation_materializes_from_local_state() -> None:
    local = validate_work_analysis_local_aggregation(
        _local(), allowed_evidence_refs={"ev-1"}
    )

    result = _materialize(local)

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
    assert result["risks"] == []
    assert result["action_necessity"] == "REQUIRED"


@pytest.mark.parametrize("relation_type", ["DUPLICATES", "CONFLICTS_WITH"])
def test_guarded_relation_fails_closed_without_deterministic_validator(
    relation_type: str,
) -> None:
    local = validate_work_analysis_local_aggregation(
        _local(relation_type=relation_type), allowed_evidence_refs={"ev-1"}
    )

    with pytest.raises(WorkAnalysisV2ValidationError, match="deterministic relation validation"):
        _materialize(local)


def test_exact_duplicate_validator_can_promote_relation_and_suppress_action() -> None:
    local = validate_work_analysis_local_aggregation(
        _local(relation_type="DUPLICATES"), allowed_evidence_refs={"ev-1"}
    )

    result = _materialize(
        local,
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
    local = validate_work_analysis_local_aggregation(
        _local(relation_type="CONFLICTS_WITH"), allowed_evidence_refs={"ev-1"}
    )

    result = _materialize(
        local,
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


def test_risk_requires_explicit_validated_input_not_local_candidate_field() -> None:
    local = validate_work_analysis_local_aggregation(
        _local(), allowed_evidence_refs={"ev-1"}
    )
    result = materialize_complete_work_analysis_result_v2(
        local,
        meta=_meta(),
        allowed_evidence_refs={"ev-1"},
        validated_risks=[
            {
                "code": "SCHEDULE_RISK_VALIDATED",
                "severity": "WARNING",
                "description": "validated outside Product Prompt candidate authority",
                "evidence_refs": ["ev-1"],
            }
        ],
        policy_confirmation_receipt_refs=[],
    )
    assert result["risks"][0]["code"] == "SCHEDULE_RISK_VALIDATED"
