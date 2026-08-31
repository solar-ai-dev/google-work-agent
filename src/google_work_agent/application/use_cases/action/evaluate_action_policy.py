"""Compute the canonical deterministic Action policy decision without I/O."""

from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash

_PolicyConfirmationKind = Literal["SCOPE_EXPANSION", "DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"]


@dataclass(frozen=True, slots=True)
class EvaluateActionPolicyQueryV1:
    schema_version: Literal[1]
    run_id: str
    action_id: str
    action_version: int
    tool_id: str
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
    arguments_hash: str
    source_snapshot_ref: str
    policy_version: str
    required_scopes_granted: bool
    evidence_count: int
    evidence_refs: tuple[str, ...]
    independent_evidence_count: int = 0
    target_is_user_selected: bool = False
    has_explicit_resource_relation: bool = False
    scope_expansion_required: bool = False
    duplicate_detected: bool = False
    conflict_detected: bool = False
    feasibility_blocked: bool = False
    policy_confirmation_receipt_refs: tuple[str, ...] = ()
    policy_confirmation_receipts: tuple[PolicyConfirmationReceiptV1, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionPolicyEvaluationResultV1:
    schema_version: Literal[1]
    decision: Literal["ALLOW", "DENY", "CONFIRMATION_REQUIRED"]
    policy_version: str
    reason_codes: tuple[str, ...]
    confirmation_kind: _PolicyConfirmationKind | None


class EvaluateActionPolicyHandler:
    """Apply 01-B policy alternatives to already-resolved bounded facts."""

    def __call__(self, query: EvaluateActionPolicyQueryV1) -> ActionPolicyEvaluationResultV1:
        denied: list[str] = []
        if not query.required_scopes_granted:
            denied.append("REQUIRED_SCOPE_MISSING")
        if query.feasibility_blocked:
            denied.append("FEASIBILITY_BLOCKED")
        evidence_decision = _evaluate_evidence_policy(
            evidence_count=query.evidence_count,
            independent_evidence_count=query.independent_evidence_count,
            requires_existing_resource=query.effect in {"UPDATE", "DELETE"},
            target_is_user_selected=query.target_is_user_selected,
            has_explicit_resource_relation=query.has_explicit_resource_relation,
        )
        if evidence_decision is not None and evidence_decision[0] == "DENY":
            denied.append(evidence_decision[1])
        if denied:
            return self._result(query, "DENY", tuple(denied))

        if evidence_decision is not None:
            return self._confirmation(
                query,
                kind="SCOPE_EXPANSION",
                reason=evidence_decision[1],
            )

        if query.scope_expansion_required:
            decision = self._confirmation(
                query,
                kind="SCOPE_EXPANSION",
                reason="SCOPE_EXPANSION_REQUIRED",
            )
            if decision.decision != "ALLOW":
                return decision
        if query.duplicate_detected:
            decision = self._confirmation(
                query,
                kind="DUPLICATE_OVERRIDE",
                reason="DUPLICATE_OVERRIDE_REQUIRED",
            )
            if decision.decision != "ALLOW":
                return decision
        if query.conflict_detected:
            decision = self._confirmation(
                query,
                kind="CONFLICT_OVERRIDE",
                reason="CONFLICT_OVERRIDE_REQUIRED",
            )
            if decision.decision != "ALLOW":
                return decision
        return self._result(query, "ALLOW", ())

    def _confirmation(
        self,
        query: EvaluateActionPolicyQueryV1,
        *,
        kind: _PolicyConfirmationKind,
        reason: str,
    ) -> ActionPolicyEvaluationResultV1:
        context_hash = _policy_confirmation_context_hash(query, kind)
        for receipt in query.policy_confirmation_receipts:
            if not _matches_confirmation_receipt(
                receipt,
                referenced_receipt_ids=query.policy_confirmation_receipt_refs,
                kind=kind,
                context_hash=context_hash,
            ):
                continue
            if receipt["decision"] == "APPROVED":
                return self._result(query, "ALLOW", ())
            return self._result(query, "DENY", (f"{kind}_DECLINED",))
        return self._result(query, "CONFIRMATION_REQUIRED", (reason,), kind)

    @staticmethod
    def _result(
        query: EvaluateActionPolicyQueryV1,
        decision: Literal["ALLOW", "DENY", "CONFIRMATION_REQUIRED"],
        reason_codes: tuple[str, ...],
        confirmation_kind: _PolicyConfirmationKind | None = None,
    ) -> ActionPolicyEvaluationResultV1:
        return ActionPolicyEvaluationResultV1(
            schema_version=1,
            decision=decision,
            policy_version=query.policy_version,
            reason_codes=reason_codes,
            confirmation_kind=confirmation_kind,
        )


def _policy_confirmation_context_hash(
    query: EvaluateActionPolicyQueryV1, kind: _PolicyConfirmationKind
) -> str:
    """Bind confirmation to the current Action/evidence/policy authority."""

    return calculate_canonical_json_hash(
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
    )


def _matches_confirmation_receipt(
    receipt: PolicyConfirmationReceiptV1,
    *,
    referenced_receipt_ids: tuple[str, ...],
    kind: _PolicyConfirmationKind,
    context_hash: str,
) -> bool:
    meta = receipt.get("meta")
    if not isinstance(meta, dict):
        return False
    receipt_id = meta.get("artifact_id")
    based_on = meta.get("based_on")
    expected_owner = "TOOL_ROUTE" if kind == "SCOPE_EXPANSION" else "WORK_ANALYSIS"
    return (
        receipt.get("schema_version") == 1
        and isinstance(receipt_id, str)
        and receipt_id in referenced_receipt_ids
        and meta.get("revision") == 1
        and isinstance(based_on, list)
        and bool(based_on)
        and receipt.get("confirmation_kind") == kind
        and receipt.get("semantic_owner_id") == expected_owner
        and receipt.get("decision") in {"APPROVED", "DECLINED"}
        and receipt.get("decision_context_hash") == context_hash
    )


def _evaluate_evidence_policy(
    *,
    evidence_count: int,
    independent_evidence_count: int,
    requires_existing_resource: bool,
    target_is_user_selected: bool,
    has_explicit_resource_relation: bool,
) -> tuple[Literal["DENY", "CONFIRMATION_REQUIRED"], str] | None:
    if evidence_count < 1:
        return "DENY", "EVIDENCE_REQUIRED"
    if not requires_existing_resource:
        return None
    if target_is_user_selected or independent_evidence_count >= 2 or has_explicit_resource_relation:
        return None
    return "CONFIRMATION_REQUIRED", "EXISTING_RESOURCE_AUTHORITY_CONFIRMATION_REQUIRED"


__all__ = [
    "ActionPolicyEvaluationResultV1",
    "EvaluateActionPolicyHandler",
    "EvaluateActionPolicyQueryV1",
]
