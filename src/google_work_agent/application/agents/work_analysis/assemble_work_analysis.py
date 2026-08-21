"""Assemble the official Work Analysis artifact from validated inputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)


def assemble_work_analysis(
    *,
    meta: StateArtifactMetaV1,
    work_facts: Iterable[WorkFactV1],
    validated_relations: Iterable[WorkRelationV1],
    ambiguities: Iterable[WorkAmbiguityV1],
    risks: Iterable[WorkRiskV1],
    evidence_refs: Iterable[str],
    policy_confirmation_receipt_refs: Iterable[StateArtifactRefV1],
    action_necessity: Literal["REQUIRED", "NOT_REQUIRED"],
) -> WorkAnalysisResultV2:
    """Compose only already-validated material; no semantic decisions occur here."""
    result: WorkAnalysisResultV2 = {
        "schema_version": 2,
        "meta": dict(meta),  # type: ignore[typeddict-item]
        "work_facts": [dict(item) for item in work_facts],  # type: ignore[list-item]
        "relations": [dict(item) for item in validated_relations],  # type: ignore[list-item]
        "ambiguities": [dict(item) for item in ambiguities],  # type: ignore[list-item]
        "risks": [dict(item) for item in risks],  # type: ignore[list-item]
        "evidence_refs": _unique(evidence_refs),
        "policy_confirmation_receipt_refs": [dict(item) for item in policy_confirmation_receipt_refs],  # type: ignore[list-item]
        "action_necessity": action_necessity,
    }
    return result


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            raise ValueError("reference must not be empty")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
