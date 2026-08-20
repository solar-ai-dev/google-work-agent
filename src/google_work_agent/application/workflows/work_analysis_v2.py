"""Canonical Work Analysis V2 candidate validation and artifact assembly.

This module deliberately does not switch the production LangGraph owner field.
It prepares the V2 boundary so the later runtime cut-over can be atomic:

LLM WorkAnalysisCandidateV2
    -> structural/reference validation
    -> deterministic guarded-relation validation
    -> WorkAnalysisResultV2 (COMPLETE only)

Incomplete candidates (confirmation/retrieval/route/block) are never promoted
to an official State Artifact; the owning subgraph projects those dispositions
to WorkflowSignalV1 during the runtime cut-over.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, NotRequired, Required, TypedDict, cast

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
from google_work_agent.ports import OutputSchemaDefinition


WorkAnalysisDispositionV2 = Literal[
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
]
ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED"]

_DISPOSITIONS = {
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
}
_GUARDED_RELATION_TYPES = {"DUPLICATES", "CONFLICTS_WITH"}
_RISK_SEVERITIES = {"INFO", "WARNING", "BLOCKING"}


class WorkRelationCandidateV2(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]


class WorkAnalysisCandidateV2(TypedDict):
    schema_version: Required[Literal[2]]
    work_facts: list[dict[str, object]]
    relation_candidates: list[WorkRelationCandidateV2]
    ambiguities: list[dict[str, object]]
    risks: list[dict[str, object]]
    evidence_refs: list[str]
    disposition: WorkAnalysisDispositionV2


class RelationValidationOutcomeV1(TypedDict):
    """Deterministic adapter output for a guarded relation candidate.

    The adapter may reuse the existing Task/Calendar domain evaluators, but
    Work Analysis never depends on Planning/Write argument adapters.
    """

    accepted: bool
    validator_codes: list[str]
    ambiguity: NotRequired[WorkAmbiguityV1 | None]
    risk: NotRequired[WorkRiskV1 | None]
    action_necessity: NotRequired[ActionNecessityV1]


RelationValidator = Callable[[WorkRelationCandidateV2], RelationValidationOutcomeV1]


WORK_ANALYSIS_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-analysis-candidate-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "work_facts",
            "relation_candidates",
            "ambiguities",
            "risks",
            "evidence_refs",
            "disposition",
        ],
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "work_facts": {"type": "array", "items": {"type": "object"}},
            "relation_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "relation_type",
                        "left_ref",
                        "right_ref",
                        "evidence_refs",
                    ],
                    "properties": {
                        "relation_type": {"type": "string"},
                        "left_ref": {"type": "string"},
                        "right_ref": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                },
            },
            "ambiguities": {"type": "array", "items": {"type": "object"}},
            "risks": {"type": "array", "items": {"type": "object"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "disposition": {"type": "string", "enum": sorted(_DISPOSITIONS)},
        },
    },
)


class WorkAnalysisV2ValidationError(ValueError):
    """Candidate or deterministic post-validation result violates V2 contract."""


def validate_work_analysis_candidate_v2(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> WorkAnalysisCandidateV2:
    root = _mapping(value, "$")
    _exact_keys(
        root,
        path="$",
        required={
            "schema_version",
            "work_facts",
            "relation_candidates",
            "ambiguities",
            "risks",
            "evidence_refs",
            "disposition",
        },
    )
    if root["schema_version"] != 2:
        raise WorkAnalysisV2ValidationError("$.schema_version must be 2")
    disposition = _text(root["disposition"], "$.disposition")
    if disposition not in _DISPOSITIONS:
        raise WorkAnalysisV2ValidationError("$.disposition is invalid")

    top_evidence = _evidence_refs(
        root["evidence_refs"], path="$.evidence_refs", allowed=allowed_evidence_refs
    )
    top_evidence_set = set(top_evidence)

    work_facts: list[dict[str, object]] = []
    for index, raw in enumerate(_list(root["work_facts"], "$.work_facts")):
        fact = _project_fact_candidate(raw, f"$.work_facts[{index}]", allowed_evidence_refs)
        _require_nested_refs_in_top_level(
            fact["evidence_refs"], top_evidence_set, f"$.work_facts[{index}].evidence_refs"
        )
        work_facts.append(cast(dict[str, object], fact))

    relation_candidates: list[WorkRelationCandidateV2] = []
    for index, raw in enumerate(
        _list(root["relation_candidates"], "$.relation_candidates")
    ):
        relation = _relation_candidate(
            raw, f"$.relation_candidates[{index}]", allowed_evidence_refs
        )
        _require_nested_refs_in_top_level(
            relation["evidence_refs"],
            top_evidence_set,
            f"$.relation_candidates[{index}].evidence_refs",
        )
        relation_candidates.append(relation)

    ambiguities: list[dict[str, object]] = []
    for index, raw in enumerate(_list(root["ambiguities"], "$.ambiguities")):
        ambiguity = _project_ambiguity_candidate(
            raw, f"$.ambiguities[{index}]", allowed_evidence_refs
        )
        _require_nested_refs_in_top_level(
            ambiguity["evidence_refs"],
            top_evidence_set,
            f"$.ambiguities[{index}].evidence_refs",
        )
        ambiguities.append(cast(dict[str, object], ambiguity))

    risks: list[dict[str, object]] = []
    for index, raw in enumerate(_list(root["risks"], "$.risks")):
        risk = _project_risk_candidate(raw, f"$.risks[{index}]", allowed_evidence_refs)
        _require_nested_refs_in_top_level(
            risk["evidence_refs"], top_evidence_set, f"$.risks[{index}].evidence_refs"
        )
        risks.append(cast(dict[str, object], risk))

    return {
        "schema_version": 2,
        "work_facts": work_facts,
        "relation_candidates": relation_candidates,
        "ambiguities": ambiguities,
        "risks": risks,
        "evidence_refs": top_evidence,
        "disposition": cast(WorkAnalysisDispositionV2, disposition),
    }


def materialize_complete_work_analysis_result_v2(
    candidate: WorkAnalysisCandidateV2,
    *,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
    policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1] = (),
    relation_validator: RelationValidator | None = None,
) -> WorkAnalysisResultV2:
    """Promote one COMPLETE candidate into the official V2 artifact.

    Non-COMPLETE candidates intentionally cannot become Main-State business
    artifacts. Guarded duplicate/conflict relations fail closed unless a
    deterministic adapter is supplied.
    """

    if candidate["disposition"] != "COMPLETE":
        raise WorkAnalysisV2ValidationError(
            "only COMPLETE Work Analysis candidates may become official artifacts"
        )

    facts = [
        _fact_from_projected(value, f"$.work_facts[{index}]", allowed_evidence_refs)
        for index, value in enumerate(candidate["work_facts"])
    ]
    ambiguities = [
        _ambiguity_from_projected(
            value, f"$.ambiguities[{index}]", allowed_evidence_refs
        )
        for index, value in enumerate(candidate["ambiguities"])
    ]
    risks = [
        _risk_from_projected(value, f"$.risks[{index}]", allowed_evidence_refs)
        for index, value in enumerate(candidate["risks"])
    ]

    relations: list[WorkRelationV1] = []
    action_necessity: ActionNecessityV1 = "REQUIRED"
    for relation in candidate["relation_candidates"]:
        if relation["relation_type"] not in _GUARDED_RELATION_TYPES:
            relations.append({**relation, "validator_codes": []})
            continue
        if relation_validator is None:
            raise WorkAnalysisV2ValidationError(
                f"{relation['relation_type']} requires deterministic relation validation"
            )
        outcome = relation_validator(relation)
        validator_codes = _string_list(
            outcome.get("validator_codes"), "$.relation_validation.validator_codes"
        )
        if not validator_codes:
            raise WorkAnalysisV2ValidationError(
                "guarded relation validation requires at least one validator code"
            )
        if outcome.get("accepted") is True:
            relations.append({**relation, "validator_codes": validator_codes})
        else:
            ambiguity = outcome.get("ambiguity")
            risk = outcome.get("risk")
            if ambiguity is not None:
                ambiguities.append(
                    _ambiguity_from_projected(
                        cast(Mapping[str, object], ambiguity),
                        "$.relation_validation.ambiguity",
                        allowed_evidence_refs,
                    )
                )
            if risk is not None:
                risks.append(
                    _risk_from_projected(
                        cast(Mapping[str, object], risk),
                        "$.relation_validation.risk",
                        allowed_evidence_refs,
                    )
                )
        requested_necessity = outcome.get("action_necessity")
        if requested_necessity is not None:
            if requested_necessity not in {"REQUIRED", "NOT_REQUIRED"}:
                raise WorkAnalysisV2ValidationError(
                    "relation validator returned invalid action_necessity"
                )
            if requested_necessity == "NOT_REQUIRED":
                action_necessity = "NOT_REQUIRED"

    return {
        "schema_version": 2,
        "meta": _artifact_meta(meta),
        "work_facts": facts,
        "relations": relations,
        "ambiguities": ambiguities,
        "risks": risks,
        "evidence_refs": _evidence_refs(
            candidate["evidence_refs"],
            path="$.evidence_refs",
            allowed=allowed_evidence_refs,
        ),
        "policy_confirmation_receipt_refs": [
            _artifact_ref(value, f"$.policy_confirmation_receipt_refs[{index}]")
            for index, value in enumerate(policy_confirmation_receipt_refs)
        ],
        "action_necessity": action_necessity,
    }


def _project_fact_candidate(
    value: object, path: str, allowed: set[str]
) -> WorkFactV1:
    item = _mapping(value, path)
    return _fact_from_projected(item, path, allowed)


def _fact_from_projected(
    value: Mapping[str, object], path: str, allowed: set[str]
) -> WorkFactV1:
    fact_id = _text(value.get("fact_id"), f"{path}.fact_id")
    fact_type = _text(value.get("fact_type"), f"{path}.fact_type")
    raw_value = value.get("value")
    if isinstance(raw_value, str):
        fact_value: str | list[str] = _text(raw_value, f"{path}.value")
    else:
        fact_value = _string_list(raw_value, f"{path}.value")
    return {
        "fact_id": fact_id,
        "fact_type": fact_type,
        "value": fact_value,
        "evidence_refs": _evidence_refs(
            value.get("evidence_refs"), path=f"{path}.evidence_refs", allowed=allowed
        ),
    }


def _relation_candidate(
    value: object, path: str, allowed: set[str]
) -> WorkRelationCandidateV2:
    item = _mapping(value, path)
    _exact_keys(
        item,
        path=path,
        required={"relation_type", "left_ref", "right_ref", "evidence_refs"},
    )
    evidence_refs = _evidence_refs(
        item["evidence_refs"], path=f"{path}.evidence_refs", allowed=allowed
    )
    if not evidence_refs:
        raise WorkAnalysisV2ValidationError(f"{path}.evidence_refs must not be empty")
    return {
        "relation_type": _text(item["relation_type"], f"{path}.relation_type"),
        "left_ref": _text(item["left_ref"], f"{path}.left_ref"),
        "right_ref": _text(item["right_ref"], f"{path}.right_ref"),
        "evidence_refs": evidence_refs,
    }


def _project_ambiguity_candidate(
    value: object, path: str, allowed: set[str]
) -> WorkAmbiguityV1:
    return _ambiguity_from_projected(_mapping(value, path), path, allowed)


def _ambiguity_from_projected(
    value: Mapping[str, object], path: str, allowed: set[str]
) -> WorkAmbiguityV1:
    return {
        "code": _text(value.get("code"), f"{path}.code"),
        "description": _text(value.get("description"), f"{path}.description"),
        "evidence_refs": _evidence_refs(
            value.get("evidence_refs"), path=f"{path}.evidence_refs", allowed=allowed
        ),
    }


def _project_risk_candidate(value: object, path: str, allowed: set[str]) -> WorkRiskV1:
    return _risk_from_projected(_mapping(value, path), path, allowed)


def _risk_from_projected(
    value: Mapping[str, object], path: str, allowed: set[str]
) -> WorkRiskV1:
    severity = _text(value.get("severity"), f"{path}.severity")
    if severity not in _RISK_SEVERITIES:
        raise WorkAnalysisV2ValidationError(f"{path}.severity is invalid")
    return {
        "code": _text(value.get("code"), f"{path}.code"),
        "severity": cast(Literal["INFO", "WARNING", "BLOCKING"], severity),
        "description": _text(value.get("description"), f"{path}.description"),
        "evidence_refs": _evidence_refs(
            value.get("evidence_refs"), path=f"{path}.evidence_refs", allowed=allowed
        ),
    }


def _artifact_meta(value: Mapping[str, object]) -> StateArtifactMetaV1:
    item = _mapping(value, "$.meta")
    _exact_keys(item, path="$.meta", required={"artifact_id", "revision", "based_on"})
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError("$.meta.revision must be a positive integer")
    based_on = _list(item["based_on"], "$.meta.based_on")
    return {
        "artifact_id": _text(item["artifact_id"], "$.meta.artifact_id"),
        "revision": revision,
        "based_on": [
            _artifact_ref(raw, f"$.meta.based_on[{index}]")
            for index, raw in enumerate(based_on)
        ],
    }


def _artifact_ref(value: object, path: str) -> StateArtifactRefV1:
    item = _mapping(value, path)
    _exact_keys(item, path=path, required={"artifact_id", "revision"})
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError(f"{path}.revision must be a positive integer")
    return {
        "artifact_id": _text(item["artifact_id"], f"{path}.artifact_id"),
        "revision": revision,
    }


def _evidence_refs(value: object, *, path: str, allowed: set[str]) -> list[str]:
    refs = _string_list(value, path)
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        raise WorkAnalysisV2ValidationError(f"{path} contains unknown evidence refs: {unknown}")
    if len(refs) != len(set(refs)):
        raise WorkAnalysisV2ValidationError(f"{path} contains duplicate evidence refs")
    return refs


def _require_nested_refs_in_top_level(
    refs: Sequence[str], top_level: set[str], path: str
) -> None:
    missing = [ref for ref in refs if ref not in top_level]
    if missing:
        raise WorkAnalysisV2ValidationError(
            f"{path} must also be listed in top-level evidence_refs: {missing}"
        )


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise WorkAnalysisV2ValidationError(f"{path} must be an object")
    return {str(key): item for key, item in value.items()}


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkAnalysisV2ValidationError(f"{path} must be an array")
    return list(value)


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkAnalysisV2ValidationError(f"{path} must be a non-empty string")
    return value


def _string_list(value: object, path: str) -> list[str]:
    values = _list(value, path)
    result: list[str] = []
    for index, item in enumerate(values):
        result.append(_text(item, f"{path}[{index}]"))
    return result


def _exact_keys(
    value: Mapping[str, object], *, path: str, required: set[str]
) -> None:
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing or extra:
        raise WorkAnalysisV2ValidationError(
            f"{path} keys mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )


__all__ = [
    "ActionNecessityV1",
    "RelationValidationOutcomeV1",
    "RelationValidator",
    "WORK_ANALYSIS_CANDIDATE_OUTPUT_SCHEMA",
    "WorkAnalysisCandidateV2",
    "WorkAnalysisDispositionV2",
    "WorkAnalysisV2ValidationError",
    "WorkRelationCandidateV2",
    "materialize_complete_work_analysis_result_v2",
    "validate_work_analysis_candidate_v2",
]
