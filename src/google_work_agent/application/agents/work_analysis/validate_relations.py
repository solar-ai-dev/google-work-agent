"""Deterministically validate Work Analysis relation candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, TypedDict, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)

ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED"]
_GUARDED = frozenset({"DUPLICATES", "CONFLICTS_WITH"})


class RelationValidationOutcomeV1(TypedDict, total=False):
    accepted: bool
    validator_codes: list[str]
    ambiguity: WorkAmbiguityV1 | None
    risk: WorkRiskV1 | None
    action_necessity: ActionNecessityV1


class RelationValidationBundleV1(TypedDict):
    validated_relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    action_necessity: ActionNecessityV1


RelationValidator = Callable[[Mapping[str, object], WorkFactV1, WorkFactV1], RelationValidationOutcomeV1]


def validate_relations(
    relation_candidates: Sequence[Mapping[str, object]],
    *,
    work_facts: Sequence[WorkFactV1],
    validator: RelationValidator,
) -> RelationValidationBundleV1:
    """Validate relations before any duplicate/conflict candidate becomes official."""
    facts = {fact["fact_id"]: fact for fact in work_facts}
    if len(facts) != len(work_facts):
        raise ValueError("duplicate work fact id")
    relations: list[WorkRelationV1] = []
    ambiguities: list[WorkAmbiguityV1] = []
    risks: list[WorkRiskV1] = []
    action_necessity: ActionNecessityV1 = "REQUIRED"

    for raw in relation_candidates:
        relation_type = _text(raw.get("relation_type"), "relation_type")
        left_ref = _text(raw.get("left_ref"), "left_ref")
        right_ref = _text(raw.get("right_ref"), "right_ref")
        if left_ref == right_ref:
            raise ValueError("relation cannot reference the same fact twice")
        left = facts.get(left_ref)
        right = facts.get(right_ref)
        if left is None or right is None:
            raise ValueError("relation references an unknown work fact")
        evidence_refs = _strings(raw.get("evidence_refs"), "evidence_refs")
        outcome = validator(raw, left, right)
        codes = _strings(outcome.get("validator_codes", []), "validator_codes")
        accepted = bool(outcome.get("accepted"))
        if relation_type in _GUARDED and not codes:
            raise ValueError("guarded relation requires deterministic validator codes")
        ambiguity = outcome.get("ambiguity")
        risk = outcome.get("risk")
        if ambiguity is not None:
            ambiguities.append(cast(WorkAmbiguityV1, dict(ambiguity)))
        if risk is not None:
            risks.append(cast(WorkRiskV1, dict(risk)))
        necessity = outcome.get("action_necessity")
        if necessity is not None:
            if necessity not in {"REQUIRED", "NOT_REQUIRED"}:
                raise ValueError("invalid action necessity")
            if necessity == "NOT_REQUIRED":
                action_necessity = "NOT_REQUIRED"
        if accepted:
            relations.append({
                "relation_type": relation_type,
                "left_ref": left_ref,
                "right_ref": right_ref,
                "evidence_refs": evidence_refs,
                "validator_codes": codes,
            })
    return {
        "validated_relations": relations,
        "ambiguities": ambiguities,
        "risks": risks,
        "action_necessity": action_necessity,
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    result = list(value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicates")
    return result
