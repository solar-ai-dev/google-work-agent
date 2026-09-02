from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    assemble_work_analysis,
    work_analysis_confirmation_context_hash,
)
from tests.support.work_analysis import fact


def test_exact_duplicate_defaults__to_not_required__without_llm_policy_authority() -> None:
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=[{"artifact_id": "intent-1", "revision": 1}],
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        action_necessity_candidate="NOT_REQUIRED",
        action_necessity_reason="llm opinion",
        policy_confirmation_receipts=[],
    )

    assert result["action_necessity"] == "NOT_REQUIRED"
    assert result["action_necessity_reason"] == "EXACT_DUPLICATE_ALREADY_SATISFIES_REQUEST"
    assert result["policy_confirmation_receipt_refs"] == []


def test_duplicate_required__candidate_stays__undetermined_without_receipt() -> None:
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=[{"artifact_id": "intent-1", "revision": 1}],
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        action_necessity_candidate="REQUIRED",
        action_necessity_reason="llm opinion",
        policy_confirmation_receipts=[],
    )

    assert result["action_necessity"] == "UNDETERMINED"
    assert result["action_necessity_reason"] == "DUPLICATE_OVERRIDE_REQUIRED"


def test_current_approved_duplicate__override_receipt_is__bound_into_result() -> None:
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    receipt = {
        "schema_version": 1,
        "meta": {"artifact_id": "receipt-1", "revision": 1, "based_on": based_on},
        "interrupt_id": "interrupt-1",
        "confirmation_kind": "DUPLICATE_OVERRIDE",
        "decision": "APPROVED",
        "semantic_owner_id": "WORK_ANALYSIS",
        "decision_context_hash": work_analysis_confirmation_context_hash(
            confirmation_kind="DUPLICATE_OVERRIDE",
            interrupt_id="interrupt-1",
            based_on=based_on,  # type: ignore[arg-type]
        ),
        "affected_route_ids": [],
        "affected_resource_refs": [],
    }
    result = assemble_work_analysis(
        artifact_id="analysis-1",
        revision=1,
        based_on=based_on,  # type: ignore[arg-type]
        work_facts=[fact("f1"), fact("f2")],
        validated_relations=[
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ],
        ambiguities=[],
        risks=[],
        evidence_refs=["ev-1"],
        action_necessity_candidate="REQUIRED",
        action_necessity_reason="candidate",
        policy_confirmation_receipts=[receipt],  # type: ignore[list-item]
    )

    assert result["action_necessity"] == "REQUIRED"
    assert result["policy_confirmation_receipt_refs"] == [
        {"artifact_id": "receipt-1", "revision": 1}
    ]
    assert {"artifact_id": "receipt-1", "revision": 1} in result["meta"]["based_on"]
