from __future__ import annotations

from inspect import signature

import pytest

import google_work_agent.application.workflows.work_analysis_v2 as work_analysis_v2
from google_work_agent.application.workflows.work_analysis_v2 import (
    WorkAnalysisV2ValidationError,
    materialize_complete_work_analysis_result_v2,
    project_work_analysis_confirmation_required_v1,
    project_work_analysis_retrieval_required_v1,
    validate_and_merge_work_analysis_risks,
    validate_work_analysis_local_aggregation,
)


def _local(*, relation_type: str = "DEPENDS_ON", right_ref: str = "fact-2"):
    return {
        "fact_candidates": [
            {"fact_id": "fact-1", "fact_type": "TASK", "value": "submit report", "evidence_refs": ["ev-1"]},
            {"fact_id": "fact-2", "fact_type": "TASK", "value": "submit report", "evidence_refs": ["ev-2"]},
        ],
        "relation_candidates": [
            {"relation_type": relation_type, "left_ref": "fact-1", "right_ref": right_ref, "evidence_refs": ["ev-1", "ev-2"]}
        ],
        "relation_validation_ambiguities": [],
        "ambiguity_candidates": [],
        "risk_candidates": [],
        "relation_validation_risks": [],
        "validated_risks": [],
        "gap_decision": {"disposition": "COMPLETE"},
        "evidence_refs": ["ev-1", "ev-2"],
    }


def _meta():
    return {"artifact_id": "analysis-1", "revision": 1, "based_on": [{"artifact_id": "retrieval-1", "revision": 1}]}


def _identity_resolver(fact):
    return [{"resource_type": "task", "resource_id": "t1" if fact["fact_id"] == "fact-1" else "t2", "parent_id": "list-1"}]


def _materialize(local, *, relation_validator=None, fact_identity_resolver=None):
    return materialize_complete_work_analysis_result_v2(
        local,
        meta=_meta(),
        allowed_evidence_refs={"ev-1", "ev-2"},
        policy_confirmation_receipt_refs=[],
        relation_validator=relation_validator,
        fact_identity_resolver=fact_identity_resolver,
    )


def test_local_aggregation_is_not_a_product_prompt_or_main_state_schema() -> None:
    assert not hasattr(work_analysis_v2, "WORK_ANALYSIS_CANDIDATE_OUTPUT_SCHEMA")
    assert not hasattr(work_analysis_v2, "WorkAnalysisCandidateV2")
    assert "validated_risks" not in signature(materialize_complete_work_analysis_result_v2).parameters


def test_gap_needs_more_data_projects_exact_retrieval_needs_without_synthesis() -> None:
    decision = {
        "disposition": "NEEDS_MORE_DATA",
        "needs": [{"required_information": "recipient email chosen by assess_analysis_gaps", "reason_codes": ["MISSING_RECIPIENT"]}],
    }
    signal = project_work_analysis_retrieval_required_v1(decision)
    assert signal == {"kind": "RETRIEVAL_REQUIRED", "reason_codes": ["MISSING_RECIPIENT"], "needs": decision["needs"]}


def test_gap_confirmation_attaches_only_application_owned_resume_metadata() -> None:
    decision = {
        "disposition": "NEEDS_CONFIRMATION",
        "question": "Which task should be updated?",
        "options": ["Task A", "Task B"],
        "reason_codes": ["TARGET_AMBIGUOUS"],
    }
    signal = project_work_analysis_confirmation_required_v1(
        decision,
        interrupt_id="interrupt-1",
        resume_target={"subgraph_id": "WORK_ANALYSIS", "node_id": "finalize", "graph_version": "v1"},
    )
    assert signal["question"] == decision["question"]
    assert signal["options"] == decision["options"]
    assert signal["interrupt_id"] == "interrupt-1"
    assert signal["owner_subgraph"] == "WORK_ANALYSIS"
    assert "reason_codes" not in signal


def test_relation_operands_must_be_same_invocation_fact_ids() -> None:
    with pytest.raises(WorkAnalysisV2ValidationError, match="WorkFactV1.fact_id"):
        validate_work_analysis_local_aggregation(_local(right_ref="task:t2"), allowed_evidence_refs={"ev-1", "ev-2"})


def test_guarded_relation_does_not_promote_when_operand_identity_is_not_exactly_one() -> None:
    local = validate_work_analysis_local_aggregation(_local(relation_type="DUPLICATES"), allowed_evidence_refs={"ev-1", "ev-2"})
    validator_called = False

    def validator(_input):
        nonlocal validator_called
        validator_called = True
        return {"accepted": True, "validator_codes": ["EXACT"]}

    result = _materialize(
        local,
        relation_validator=validator,
        fact_identity_resolver=lambda fact: [] if fact["fact_id"] == "fact-2" else _identity_resolver(fact),
    )
    assert validator_called is False
    assert result["relations"] == []
    assert result["ambiguities"][0]["code"] == "RELATION_OPERAND_IDENTITY_UNRESOLVED"


def test_exact_duplicate_uses_fact_identity_input_and_can_suppress_action() -> None:
    local = validate_work_analysis_local_aggregation(_local(relation_type="DUPLICATES"), allowed_evidence_refs={"ev-1", "ev-2"})

    def validator(input_value):
        assert input_value["relation"]["left_ref"] == "fact-1"
        assert input_value["left_fact"]["fact_id"] == "fact-1"
        assert input_value["right_fact"]["fact_id"] == "fact-2"
        assert input_value["left_identity"]["resource_id"] == "t1"
        assert input_value["right_identity"]["resource_id"] == "t2"
        return {"accepted": True, "validator_codes": ["TASK_EXACT_DUPLICATE_VALIDATED"], "action_necessity": "NOT_REQUIRED"}

    result = _materialize(local, relation_validator=validator, fact_identity_resolver=_identity_resolver)
    assert result["relations"][0]["relation_type"] == "DUPLICATES"
    assert result["action_necessity"] == "NOT_REQUIRED"


def test_risks_merge_semantic_and_relation_sources_deterministically() -> None:
    risk = {"code": "SCHEDULE_RISK", "severity": "WARNING", "description": "same evidence-backed risk", "evidence_refs": ["ev-1"]}
    result = validate_and_merge_work_analysis_risks(
        risk_candidates=[risk],
        relation_validation_risks=[risk],
        allowed_evidence_refs={"ev-1", "ev-2"},
    )
    assert result == [risk]


def test_conflicting_duplicate_risk_code_fails_closed() -> None:
    with pytest.raises(WorkAnalysisV2ValidationError, match="conflicting payload"):
        validate_and_merge_work_analysis_risks(
            risk_candidates=[{"code": "RISK", "severity": "WARNING", "description": "one", "evidence_refs": ["ev-1"]}],
            relation_validation_risks=[{"code": "RISK", "severity": "INFO", "description": "two", "evidence_refs": ["ev-1"]}],
            allowed_evidence_refs={"ev-1", "ev-2"},
        )


def test_blocking_risk_cannot_materialize_complete_artifact() -> None:
    local = _local()
    local["risk_candidates"] = [{"code": "UNRESOLVED_BLOCKER", "severity": "BLOCKING", "description": "must be blocked before Domain", "evidence_refs": ["ev-1"]}]
    with pytest.raises(WorkAnalysisV2ValidationError, match="BLOCKED disposition"):
        _materialize(local)
