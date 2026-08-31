"""Canonical Planning ANSWER candidate validation and artifact assembly."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.planning.contracts.answer_draft import AnswerDraftV2
from google_work_agent.application.agents.state_artifact import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.ports.llm import OutputSchemaDefinition


class AnswerDraftCandidateV2(TypedDict):
    schema_version: Required[Literal[2]]
    answer: str
    evidence_refs: list[str]


ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="answer-draft-candidate-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "answer", "evidence_refs"],
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "answer": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
    },
)


class PlanningAnswerV2ValidationError(ValueError):
    """Answer candidate or official AnswerDraftV2 violates the canonical contract."""


def validate_answer_draft_candidate_v2(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> AnswerDraftCandidateV2:
    root = _mapping(value, "$")
    required = {"schema_version", "answer", "evidence_refs"}
    if set(root) != required:
        missing = required - set(root)
        extra = set(root) - required
        raise PlanningAnswerV2ValidationError(
            f"$ keys mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )
    if root["schema_version"] != 2:
        raise PlanningAnswerV2ValidationError("$.schema_version must be 2")
    answer = root["answer"]
    if not isinstance(answer, str):
        raise PlanningAnswerV2ValidationError("$.answer must be a string")
    evidence_refs = _evidence_refs(
        root["evidence_refs"],
        path="$.evidence_refs",
        allowed=allowed_evidence_refs,
    )
    return {
        "schema_version": 2,
        "answer": answer,
        "evidence_refs": evidence_refs,
    }


def materialize_answer_draft_v2(
    candidate: AnswerDraftCandidateV2,
    *,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
) -> AnswerDraftV2:
    """Promote one validated ANSWER candidate into the official Planning artifact."""

    validated = validate_answer_draft_candidate_v2(
        candidate,
        allowed_evidence_refs=allowed_evidence_refs,
    )
    return {
        "schema_version": 2,
        "meta": _artifact_meta(meta),
        "answer": validated["answer"],
        "evidence_refs": list(validated["evidence_refs"]),
    }


def _artifact_meta(value: object) -> StateArtifactMetaV1:
    root = _mapping(value, "$.meta")
    required = {"artifact_id", "revision", "based_on"}
    if set(root) != required:
        raise PlanningAnswerV2ValidationError("$.meta keys are invalid")
    artifact_id = root["artifact_id"]
    revision = root["revision"]
    based_on = root["based_on"]
    if not isinstance(artifact_id, str) or not artifact_id:
        raise PlanningAnswerV2ValidationError("$.meta.artifact_id must be non-empty")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PlanningAnswerV2ValidationError("$.meta.revision must be positive")
    if not isinstance(based_on, list):
        raise PlanningAnswerV2ValidationError("$.meta.based_on must be an array")
    refs: list[StateArtifactRefV1] = []
    for index, raw in enumerate(based_on):
        item = _mapping(raw, f"$.meta.based_on[{index}]")
        if set(item) != {"artifact_id", "revision"}:
            raise PlanningAnswerV2ValidationError(f"$.meta.based_on[{index}] keys are invalid")
        ref_id = item["artifact_id"]
        ref_revision = item["revision"]
        if not isinstance(ref_id, str) or not ref_id:
            raise PlanningAnswerV2ValidationError(
                f"$.meta.based_on[{index}].artifact_id must be non-empty"
            )
        if not isinstance(ref_revision, int) or isinstance(ref_revision, bool) or ref_revision < 1:
            raise PlanningAnswerV2ValidationError(
                f"$.meta.based_on[{index}].revision must be positive"
            )
        refs.append({"artifact_id": ref_id, "revision": ref_revision})
    return {
        "artifact_id": artifact_id,
        "revision": revision,
        "based_on": refs,
    }


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PlanningAnswerV2ValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlanningAnswerV2ValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _evidence_refs(value: object, *, path: str, allowed: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanningAnswerV2ValidationError(f"{path} must be a string array")
    refs = list(value)
    if len(refs) != len(set(refs)):
        raise PlanningAnswerV2ValidationError(f"{path} contains duplicates")
    unknown = set(refs) - allowed
    if unknown:
        raise PlanningAnswerV2ValidationError(
            f"{path} contains unavailable evidence refs: {sorted(unknown)}"
        )
    return refs


__all__ = [
    "ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA",
    "AnswerDraftCandidateV2",
    "PlanningAnswerV2ValidationError",
    "materialize_answer_draft_v2",
    "validate_answer_draft_candidate_v2",
]
