"""Work Analysis V2 official-artifact assembly from invocation-local state.

Only ``WorkAnalysisResultV2`` is a canonical Main-State artifact. The local
aggregation below is an implementation detail: it is not a Product Prompt
output schema, is never stored in Main State, and must not be registered in the
Prompt Manifest. Canonical gaps for control-signal payloads, guarded-relation
operand namespaces, and risk production are intentionally not guessed here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, NotRequired, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)

ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED"]
_GUARDED_RELATION_TYPES = {"DUPLICATES", "CONFLICTS_WITH"}
_RISK_SEVERITIES = {"INFO", "WARNING", "BLOCKING"}


class WorkRelationLocalCandidate(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]


class WorkAnalysisLocalAggregation(TypedDict):
    """Invocation-local scratch matching the canonical Work Analysis Local State."""

    fact_candidates: list[dict[str, object]]
    relation_candidates: list[WorkRelationLocalCandidate]
    relation_validation_ambiguities: list[dict[str, object]]
    ambiguity_candidates: list[dict[str, object]]
    evidence_refs: list[str]


class RelationValidationOutcomeV1(TypedDict):
    accepted: bool
    validator_codes: list[str]
    ambiguity: NotRequired[WorkAmbiguityV1 | None]
    risk: NotRequired[WorkRiskV1 | None]
    action_necessity: NotRequired[ActionNecessityV1]


RelationValidator = Callable[[WorkRelationLocalCandidate], RelationValidationOutcomeV1]


class WorkAnalysisV2ValidationError(ValueError):
    pass


def validate_work_analysis_local_aggregation(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> WorkAnalysisLocalAggregation:
    root = _mapping(value, "$")
    _exact(
        root,
        {
            "fact_candidates",
            "relation_candidates",
            "relation_validation_ambiguities",
            "ambiguity_candidates",
            "evidence_refs",
        },
        "$",
    )
    top = _evidence_refs(root["evidence_refs"], "$.evidence_refs", allowed_evidence_refs)
    top_set = set(top)

    facts: list[dict[str, object]] = []
    for i, raw in enumerate(_list(root["fact_candidates"], "$.fact_candidates")):
        path = f"$.fact_candidates[{i}]"
        fact = _fact(_mapping(raw, path), path, allowed_evidence_refs)
        _nested(fact["evidence_refs"], top_set, f"{path}.evidence_refs")
        facts.append(cast(dict[str, object], fact))

    relations: list[WorkRelationLocalCandidate] = []
    for i, raw in enumerate(_list(root["relation_candidates"], "$.relation_candidates")):
        path = f"$.relation_candidates[{i}]"
        relation = _relation(raw, path, allowed_evidence_refs)
        _nested(relation["evidence_refs"], top_set, f"{path}.evidence_refs")
        relations.append(relation)

    return {
        "fact_candidates": facts,
        "relation_candidates": relations,
        "relation_validation_ambiguities": _ambiguities(
            root["relation_validation_ambiguities"],
            "$.relation_validation_ambiguities",
            allowed_evidence_refs,
            top_set,
        ),
        "ambiguity_candidates": _ambiguities(
            root["ambiguity_candidates"],
            "$.ambiguity_candidates",
            allowed_evidence_refs,
            top_set,
        ),
        "evidence_refs": top,
    }


def materialize_complete_work_analysis_result_v2(
    local: WorkAnalysisLocalAggregation,
    *,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
    validated_risks: Sequence[WorkRiskV1],
    policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1],
    relation_validator: RelationValidator | None = None,
) -> WorkAnalysisResultV2:
    """Create only the official COMPLETE artifact from validated local data.

    Risks are explicit validated input because Canonical does not yet define a
    Product Prompt/local candidate producer. DUPLICATES/CONFLICTS_WITH fail
    closed without deterministic validation; their ref namespace is not parsed.
    """

    local = validate_work_analysis_local_aggregation(
        local, allowed_evidence_refs=allowed_evidence_refs
    )
    facts = [
        _fact(v, f"$.fact_candidates[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["fact_candidates"])
    ]
    ambiguities = [
        _ambiguity(v, f"$.relation_validation_ambiguities[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["relation_validation_ambiguities"])
    ]
    ambiguities += [
        _ambiguity(v, f"$.ambiguity_candidates[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["ambiguity_candidates"])
    ]
    risks = [
        _risk(cast(Mapping[str, object], v), f"$.validated_risks[{i}]", allowed_evidence_refs)
        for i, v in enumerate(validated_risks)
    ]

    relations: list[WorkRelationV1] = []
    action_necessity: ActionNecessityV1 = "REQUIRED"
    for relation in local["relation_candidates"]:
        if relation["relation_type"] not in _GUARDED_RELATION_TYPES:
            relations.append({**relation, "validator_codes": []})
            continue
        if relation_validator is None:
            raise WorkAnalysisV2ValidationError(
                f"{relation['relation_type']} requires deterministic relation validation"
            )
        outcome = relation_validator(relation)
        codes = _strings(outcome.get("validator_codes"), "$.relation_validation.validator_codes")
        if not codes:
            raise WorkAnalysisV2ValidationError("guarded relation validation requires validator code")
        if outcome.get("accepted") is True:
            relations.append({**relation, "validator_codes": codes})
        else:
            if outcome.get("ambiguity") is not None:
                ambiguities.append(
                    _ambiguity(
                        cast(Mapping[str, object], outcome["ambiguity"]),
                        "$.relation_validation.ambiguity",
                        allowed_evidence_refs,
                    )
                )
            if outcome.get("risk") is not None:
                risks.append(
                    _risk(
                        cast(Mapping[str, object], outcome["risk"]),
                        "$.relation_validation.risk",
                        allowed_evidence_refs,
                    )
                )
        necessity = outcome.get("action_necessity")
        if necessity not in {None, "REQUIRED", "NOT_REQUIRED"}:
            raise WorkAnalysisV2ValidationError("invalid action_necessity")
        if necessity == "NOT_REQUIRED":
            action_necessity = "NOT_REQUIRED"

    return {
        "schema_version": 2,
        "meta": _meta(meta),
        "work_facts": facts,
        "relations": relations,
        "ambiguities": ambiguities,
        "risks": risks,
        "evidence_refs": _evidence_refs(local["evidence_refs"], "$.evidence_refs", allowed_evidence_refs),
        "policy_confirmation_receipt_refs": [
            _artifact_ref(v, f"$.policy_confirmation_receipt_refs[{i}]")
            for i, v in enumerate(policy_confirmation_receipt_refs)
        ],
        "action_necessity": action_necessity,
    }


def _fact(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkFactV1:
    _exact(value, {"fact_id", "fact_type", "value", "evidence_refs"}, path)
    raw = value["value"]
    fact_value: str | list[str] = _text(raw, f"{path}.value") if isinstance(raw, str) else _strings(raw, f"{path}.value")
    return {
        "fact_id": _text(value["fact_id"], f"{path}.fact_id"),
        "fact_type": _text(value["fact_type"], f"{path}.fact_type"),
        "value": fact_value,
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _relation(value: object, path: str, allowed: set[str]) -> WorkRelationLocalCandidate:
    item = _mapping(value, path)
    _exact(item, {"relation_type", "left_ref", "right_ref", "evidence_refs"}, path)
    refs = _evidence_refs(item["evidence_refs"], f"{path}.evidence_refs", allowed)
    if not refs:
        raise WorkAnalysisV2ValidationError(f"{path}.evidence_refs must not be empty")
    return {
        "relation_type": _text(item["relation_type"], f"{path}.relation_type"),
        "left_ref": _text(item["left_ref"], f"{path}.left_ref"),
        "right_ref": _text(item["right_ref"], f"{path}.right_ref"),
        "evidence_refs": refs,
    }


def _ambiguities(value: object, path: str, allowed: set[str], top: set[str]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for i, raw in enumerate(_list(value, path)):
        item_path = f"{path}[{i}]"
        item = _ambiguity(_mapping(raw, item_path), item_path, allowed)
        _nested(item["evidence_refs"], top, f"{item_path}.evidence_refs")
        result.append(cast(dict[str, object], item))
    return result


def _ambiguity(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkAmbiguityV1:
    _exact(value, {"code", "description", "evidence_refs"}, path)
    return {
        "code": _text(value["code"], f"{path}.code"),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _risk(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkRiskV1:
    _exact(value, {"code", "severity", "description", "evidence_refs"}, path)
    severity = _text(value["severity"], f"{path}.severity")
    if severity not in _RISK_SEVERITIES:
        raise WorkAnalysisV2ValidationError(f"{path}.severity is invalid")
    return {
        "code": _text(value["code"], f"{path}.code"),
        "severity": cast(Literal["INFO", "WARNING", "BLOCKING"], severity),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _meta(value: object) -> StateArtifactMetaV1:
    item = _mapping(value, "$.meta")
    _exact(item, {"artifact_id", "revision", "based_on"}, "$.meta")
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError("$.meta.revision is invalid")
    return {
        "artifact_id": _text(item["artifact_id"], "$.meta.artifact_id"),
        "revision": revision,
        "based_on": [
            _artifact_ref(v, f"$.meta.based_on[{i}]")
            for i, v in enumerate(_list(item["based_on"], "$.meta.based_on"))
        ],
    }


def _artifact_ref(value: object, path: str) -> StateArtifactRefV1:
    item = _mapping(value, path)
    _exact(item, {"artifact_id", "revision"}, path)
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError(f"{path}.revision is invalid")
    return {"artifact_id": _text(item["artifact_id"], f"{path}.artifact_id"), "revision": revision}


def _evidence_refs(value: object, path: str, allowed: set[str]) -> list[str]:
    refs = _strings(value, path)
    if len(refs) != len(set(refs)):
        raise WorkAnalysisV2ValidationError(f"{path} contains duplicates")
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        raise WorkAnalysisV2ValidationError(f"{path} contains unknown evidence refs: {unknown}")
    return refs


def _nested(refs: Sequence[str], top: set[str], path: str) -> None:
    missing = [ref for ref in refs if ref not in top]
    if missing:
        raise WorkAnalysisV2ValidationError(f"{path} must also be listed in top-level evidence_refs: {missing}")


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise WorkAnalysisV2ValidationError(f"{path} must be an object with string keys")
    return dict(value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkAnalysisV2ValidationError(f"{path} must be an array")
    return list(value)


def _strings(value: object, path: str) -> list[str]:
    return [_text(v, f"{path}[{i}]") for i, v in enumerate(_list(value, path))]


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkAnalysisV2ValidationError(f"{path} must be a non-empty string")
    return value


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise WorkAnalysisV2ValidationError(f"{path} keys are invalid")


__all__ = [
    "ActionNecessityV1",
    "RelationValidationOutcomeV1",
    "RelationValidator",
    "WorkAnalysisLocalAggregation",
    "WorkAnalysisV2ValidationError",
    "WorkRelationLocalCandidate",
    "materialize_complete_work_analysis_result_v2",
    "validate_work_analysis_local_aggregation",
]
