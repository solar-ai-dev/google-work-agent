from typing import Literal

import pytest

from google_work_agent.application.orchestration.contracts import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.action.evaluate_action_policy import (
    EvaluateActionPolicyHandler,
    EvaluateActionPolicyQueryV1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash


def _query(**changes: object) -> EvaluateActionPolicyQueryV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "run_id": "run-1",
        "action_id": "action-1",
        "action_version": 1,
        "tool_id": "calendar_update_event",
        "effect": "UPDATE",
        "arguments_hash": "arguments",
        "source_snapshot_ref": "source",
        "policy_version": "policy-v1",
        "required_scopes_granted": True,
        "evidence_count": 2,
        "evidence_refs": ("evidence-1", "evidence-2"),
        "independent_evidence_count": 2,
    }
    values.update(changes)
    return EvaluateActionPolicyQueryV1(**values)  # type: ignore[arg-type]


def _receipt(
    query: EvaluateActionPolicyQueryV1,
    *,
    receipt_id: str,
    kind: Literal["SCOPE_EXPANSION", "DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"],
    decision: Literal["APPROVED", "DECLINED"],
) -> PolicyConfirmationReceiptV1:
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": receipt_id,
            "revision": 1,
            "based_on": [{"artifact_id": "work-analysis-1", "revision": 1}],
        },
        "interrupt_id": "interrupt-1",
        "confirmation_kind": kind,
        "decision": decision,
        "semantic_owner_id": (
            "TOOL_ROUTE" if kind == "SCOPE_EXPANSION" else "WORK_ANALYSIS"
        ),
        "decision_context_hash": calculate_canonical_json_hash(
            {
                "run_id": query.run_id,
                "action_id": query.action_id,
                "action_version": query.action_version,
                "tool_id": query.tool_id,
                "effect": query.effect,
                "arguments_hash": query.arguments_hash,
                "source_snapshot_ref": query.source_snapshot_ref,
                "evidence_refs": sorted(query.evidence_refs),
                "policy_version": query.policy_version,
                "confirmation_kind": kind,
            }
        ),
        "affected_route_ids": ["route-1"],
        "affected_resource_refs": ["resource-1"],
    }


@pytest.mark.parametrize(
    "authority",
    [
        {"target_is_user_selected": True, "independent_evidence_count": 0},
        {"independent_evidence_count": 2},
        {"has_explicit_resource_relation": True, "independent_evidence_count": 0},
    ],
)
def test_existing_resource_modification_accepts_each_canonical_evidence_alternative(
    authority: dict[str, object],
) -> None:
    result = EvaluateActionPolicyHandler()(_query(**authority))
    assert result.decision == "ALLOW"
    assert result.confirmation_kind is None


def test_unproven_existing_resource_requires_confirmation_instead_of_false_block() -> None:
    result = EvaluateActionPolicyHandler()(_query(evidence_count=1, independent_evidence_count=1))
    assert result.decision == "CONFIRMATION_REQUIRED"
    assert result.confirmation_kind == "SCOPE_EXPANSION"


def test_confirmation_only_unlocks_the_exact_current_context() -> None:
    current = _query(duplicate_detected=True)
    receipt = _receipt(
        current,
        receipt_id="receipt-1",
        kind="DUPLICATE_OVERRIDE",
        decision="APPROVED",
    )
    exact = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            policy_confirmation_receipt_refs=(receipt["meta"]["artifact_id"],),
            policy_confirmation_receipts=(receipt,),
        )
    )
    stale = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            source_snapshot_ref="source-v2",
            policy_confirmation_receipt_refs=(receipt["meta"]["artifact_id"],),
            policy_confirmation_receipts=(receipt,),
        )
    )
    stale_evidence = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            evidence_refs=("evidence-1", "evidence-new"),
            policy_confirmation_receipt_refs=(receipt["meta"]["artifact_id"],),
            policy_confirmation_receipts=(receipt,),
        )
    )
    unreferenced = EvaluateActionPolicyHandler()(
        _query(duplicate_detected=True, policy_confirmation_receipts=(receipt,))
    )
    assert exact.decision == "ALLOW"
    assert stale.decision == "CONFIRMATION_REQUIRED"
    assert stale.confirmation_kind == "DUPLICATE_OVERRIDE"
    assert stale_evidence.decision == "CONFIRMATION_REQUIRED"
    assert unreferenced.decision == "CONFIRMATION_REQUIRED"


def test_exact_declined_confirmation_is_denied() -> None:
    current = _query(conflict_detected=True)
    receipt = _receipt(
        current,
        receipt_id="receipt-declined",
        kind="CONFLICT_OVERRIDE",
        decision="DECLINED",
    )
    result = EvaluateActionPolicyHandler()(
        _query(
            conflict_detected=True,
            policy_confirmation_receipt_refs=(receipt["meta"]["artifact_id"],),
            policy_confirmation_receipts=(receipt,),
        )
    )
    assert result.decision == "DENY"
    assert result.reason_codes == ("CONFLICT_OVERRIDE_DECLINED",)


@pytest.mark.parametrize("invalid_field", ["semantic_owner_id", "based_on"])
def test_confirmation_receipt_requires_canonical_owner_and_provenance(
    invalid_field: str,
) -> None:
    current = _query(duplicate_detected=True)
    receipt = _receipt(
        current,
        receipt_id="receipt-invalid",
        kind="DUPLICATE_OVERRIDE",
        decision="APPROVED",
    )
    if invalid_field == "semantic_owner_id":
        receipt["semantic_owner_id"] = "TOOL_ROUTE"
    else:
        receipt["meta"]["based_on"] = []

    result = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            policy_confirmation_receipt_refs=(receipt["meta"]["artifact_id"],),
            policy_confirmation_receipts=(receipt,),
        )
    )

    assert result.decision == "CONFIRMATION_REQUIRED"
    assert result.confirmation_kind == "DUPLICATE_OVERRIDE"


@pytest.mark.parametrize(
    "changes",
    [
        {"required_scopes_granted": False},
        {"evidence_count": 0},
        {"feasibility_blocked": True},
    ],
)
def test_non_overridable_policy_failures_are_denied(changes: dict[str, object]) -> None:
    assert EvaluateActionPolicyHandler()(_query(**changes)).decision == "DENY"


def test_evaluator_exports_only_the_ledger_symbols_and_no_surrogate_receipt() -> None:
    from google_work_agent.application.use_cases.action import evaluate_action_policy

    assert evaluate_action_policy.__all__ == [
        "ActionPolicyEvaluationResultV1",
        "EvaluateActionPolicyHandler",
        "EvaluateActionPolicyQueryV1",
    ]
    assert not hasattr(evaluate_action_policy, "PolicyConfirmationEvidenceV1")
