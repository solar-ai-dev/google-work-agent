"""Deterministically validate the canonical ``WorkAnalysisResultV2`` artifact."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAnalysisResultV2,
)
from google_work_agent.application.orchestration.contracts import PolicyConfirmationReceiptV1

_FACT_KINDS = frozenset(
    {
        "TASK",
        "EVENT",
        "PERSON",
        "DATE",
        "TIME",
        "DEADLINE",
        "STATUS",
        "RESOURCE",
        "TEXT_CLAIM",
        "OTHER",
    }
)
_RELATION_KINDS = frozenset(
    {"DEPENDS_ON", "ASSIGNED_TO", "DUE_AT", "DUPLICATES", "CONFLICTS_WITH", "RELATED_TO"}
)
_RISK_KINDS = frozenset(
    {"SCHEDULE_CONFLICT", "DEADLINE_RISK", "DUPLICATE_RISK", "MISSING_INFORMATION", "OTHER"}
)


def validate_work_analysis(
    value: object,
    *,
    allowed_evidence_refs: set[str] | None = None,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1] = (),
) -> WorkAnalysisResultV2:
    if not isinstance(value, Mapping):
        raise ValueError("WorkAnalysisResultV2 must be an object")
    root = dict(value)
    expected = {
        "schema_version",
        "meta",
        "work_facts",
        "relations",
        "ambiguities",
        "risks",
        "action_necessity",
        "action_necessity_reason",
        "policy_confirmation_receipt_refs",
        "evidence_refs",
    }
    if set(root) != expected or root["schema_version"] != 2:
        raise ValueError("WorkAnalysisResultV2 keys/schema_version do not match the contract")
    top_refs = _strings(root["evidence_refs"], "evidence_refs")
    if allowed_evidence_refs is not None and not set(top_refs).issubset(allowed_evidence_refs):
        raise ValueError("WorkAnalysisResultV2 evidence is outside current RetrievalResultV1")
    top_set = set(top_refs)
    meta = _mapping(root["meta"], "meta")
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise ValueError("invalid WorkAnalysisResultV2.meta")
    _text(meta["artifact_id"], "meta.artifact_id")
    if (
        not isinstance(meta["revision"], int)
        or isinstance(meta["revision"], bool)
        or meta["revision"] < 1
    ):
        raise ValueError("meta.revision must be positive")
    based_on = {
        _artifact_ref(item, "meta.based_on") for item in _list(meta["based_on"], "meta.based_on")
    }

    facts = _object_list(root["work_facts"], "work_facts")
    fact_ids: list[str] = []
    for fact in facts:
        if set(fact) != {"fact_id", "kind", "subject", "value", "derivation", "evidence_refs"}:
            raise ValueError("invalid WorkFactV1 shape")
        fact_id = _text(fact["fact_id"], "fact_id")
        if fact["kind"] not in _FACT_KINDS or fact["derivation"] not in {"EXPLICIT", "DERIVED"}:
            raise ValueError("invalid WorkFactV1 vocabulary")
        _text(fact["subject"], "subject")
        _text(fact["value"], "value")
        _nested_refs(fact["evidence_refs"], top_set, "work_facts.evidence_refs")
        fact_ids.append(fact_id)
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("duplicate work fact id")
    fact_id_set = set(fact_ids)

    relation_ids: list[str] = []
    relation_kinds: set[str] = set()
    for relation in _object_list(root["relations"], "relations"):
        if set(relation) != {
            "relation_id",
            "kind",
            "source_fact_id",
            "target_fact_id",
            "evidence_refs",
        }:
            raise ValueError("invalid WorkRelationV1 shape")
        relation_id = _text(relation["relation_id"], "relation_id")
        kind = relation["kind"]
        source = _text(relation["source_fact_id"], "source_fact_id")
        target = _text(relation["target_fact_id"], "target_fact_id")
        if (
            kind not in _RELATION_KINDS
            or source == target
            or not {source, target}.issubset(fact_id_set)
        ):
            raise ValueError("invalid WorkRelationV1 vocabulary or operands")
        _nested_refs(relation["evidence_refs"], top_set, "relations.evidence_refs")
        relation_ids.append(relation_id)
        relation_kinds.add(cast(str, kind))
    if len(relation_ids) != len(set(relation_ids)):
        raise ValueError("duplicate work relation id")

    for ambiguity in _object_list(root["ambiguities"], "ambiguities"):
        if set(ambiguity) != {"code", "description", "requires_confirmation", "evidence_refs"}:
            raise ValueError("invalid WorkAmbiguityV1 shape")
        _text(ambiguity["code"], "ambiguity.code")
        _text(ambiguity["description"], "ambiguity.description")
        if not isinstance(ambiguity["requires_confirmation"], bool):
            raise ValueError("ambiguity.requires_confirmation must be boolean")
        _nested_refs(ambiguity["evidence_refs"], top_set, "ambiguities.evidence_refs")

    for risk in _object_list(root["risks"], "risks"):
        if set(risk) != {"kind", "severity", "description", "evidence_refs"}:
            raise ValueError("invalid WorkRiskV1 shape")
        if risk["kind"] not in _RISK_KINDS or risk["severity"] not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("invalid WorkRiskV1 vocabulary")
        _text(risk["description"], "risk.description")
        _nested_refs(risk["evidence_refs"], top_set, "risks.evidence_refs")

    necessity = root["action_necessity"]
    if necessity not in {"REQUIRED", "NOT_REQUIRED", "UNDETERMINED"}:
        raise ValueError("invalid action_necessity")
    reason = root["action_necessity_reason"]
    if reason is not None:
        _text(reason, "action_necessity_reason")
    if necessity != "UNDETERMINED" and reason is None:
        raise ValueError("determinate action necessity requires a reason")

    receipt_refs = {
        _artifact_ref(item, "policy_confirmation_receipt_refs")
        for item in _list(
            root["policy_confirmation_receipt_refs"], "policy_confirmation_receipt_refs"
        )
    }
    if not receipt_refs.issubset(based_on):
        raise ValueError("confirmation receipt refs must be present in meta.based_on")
    receipts_by_ref = {
        (item["meta"]["artifact_id"], item["meta"]["revision"]): item
        for item in policy_confirmation_receipts
    }
    for ref in receipt_refs:
        receipt = receipts_by_ref.get(ref)
        if receipt is None or receipt["semantic_owner_id"] != "WORK_ANALYSIS":
            raise ValueError("confirmation receipt ref is not current Work Analysis proof")
    if necessity == "REQUIRED" and "DUPLICATES" in relation_kinds:
        _require_approved(receipt_refs, receipts_by_ref, "DUPLICATE_OVERRIDE")
    if necessity == "REQUIRED" and "CONFLICTS_WITH" in relation_kinds:
        _require_approved(receipt_refs, receipts_by_ref, "CONFLICT_OVERRIDE")
    if necessity == "NOT_REQUIRED" and not (
        "DUPLICATES" in relation_kinds or reason == "CONFLICT_OVERRIDE_DECLINED"
    ):
        raise ValueError("NOT_REQUIRED requires deterministic duplicate/conflict grounding")
    return cast(WorkAnalysisResultV2, root)


def _require_approved(
    refs: set[tuple[str, int]],
    receipts: Mapping[tuple[str, int], PolicyConfirmationReceiptV1],
    kind: str,
) -> None:
    if not any(
        ref in refs and receipt["confirmation_kind"] == kind and receipt["decision"] == "APPROVED"
        for ref, receipt in receipts.items()
    ):
        raise ValueError(f"{kind} requires a current APPROVED receipt")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return list(value)


def _object_list(value: object, field: str) -> list[dict[str, object]]:
    return [_mapping(item, field) for item in _list(value, field)]


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _strings(value: object, field: str) -> list[str]:
    result = [_text(item, field) for item in _list(value, field)]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicates")
    return result


def _nested_refs(value: object, top: set[str], field: str) -> None:
    if not set(_strings(value, field)).issubset(top):
        raise ValueError(f"{field} is outside top-level evidence_refs")


def _artifact_ref(value: object, field: str) -> tuple[str, int]:
    item = _mapping(value, field)
    if set(item) != {"artifact_id", "revision"}:
        raise ValueError(f"{field} has invalid shape")
    artifact_id = _text(item["artifact_id"], f"{field}.artifact_id")
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError(f"{field}.revision must be positive")
    return artifact_id, revision


__all__ = ["validate_work_analysis"]
