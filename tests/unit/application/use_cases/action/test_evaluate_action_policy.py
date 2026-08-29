import pytest

from google_work_agent.application.use_cases.action.evaluate_action_policy import (
    EvaluateActionPolicyHandler,
    EvaluateActionPolicyQueryV1,
    PolicyConfirmationEvidenceV1,
    policy_confirmation_context_hash,
)


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
    receipt = PolicyConfirmationEvidenceV1(
        receipt_ref="receipt-1",
        confirmation_kind="DUPLICATE_OVERRIDE",
        decision="APPROVED",
        decision_context_hash=policy_confirmation_context_hash(current, "DUPLICATE_OVERRIDE"),
    )
    exact = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            policy_confirmation_receipt_refs=(receipt.receipt_ref,),
            policy_confirmation_receipts=(receipt,),
        )
    )
    stale = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            source_snapshot_ref="source-v2",
            policy_confirmation_receipt_refs=(receipt.receipt_ref,),
            policy_confirmation_receipts=(receipt,),
        )
    )
    stale_evidence = EvaluateActionPolicyHandler()(
        _query(
            duplicate_detected=True,
            evidence_refs=("evidence-1", "evidence-new"),
            policy_confirmation_receipt_refs=(receipt.receipt_ref,),
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
    receipt = PolicyConfirmationEvidenceV1(
        receipt_ref="receipt-declined",
        confirmation_kind="CONFLICT_OVERRIDE",
        decision="DECLINED",
        decision_context_hash=policy_confirmation_context_hash(current, "CONFLICT_OVERRIDE"),
    )
    result = EvaluateActionPolicyHandler()(
        _query(
            conflict_detected=True,
            policy_confirmation_receipt_refs=(receipt.receipt_ref,),
            policy_confirmation_receipts=(receipt,),
        )
    )
    assert result.decision == "DENY"
    assert result.reason_codes == ("CONFLICT_OVERRIDE_DECLINED",)


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
