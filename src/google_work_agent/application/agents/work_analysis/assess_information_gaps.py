"""Canonical Work Analysis semantic operation: assess_information_gaps."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapAssessmentV1,
    WorkAnalysisSemanticInputV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
)

_ALLOWED_DISPOSITIONS = frozenset(
    {
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    }
)


def assess_information_gaps(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    work_facts: Sequence[WorkFactV1],
    validated_relations: Sequence[WorkRelationV1],
    produce: Callable[
        [WorkAnalysisSemanticInputV1, Sequence[WorkFactV1], Sequence[WorkRelationV1]], object
    ],
    allowed_evidence_refs: set[str],
) -> InformationGapAssessmentV1:
    """Assess missing information only; operational risk is a separate responsibility."""
    raw = produce(semantic_input, work_facts, validated_relations)
    if not isinstance(raw, Mapping):
        raise ValueError("information-gap output must be a mapping")
    disposition = raw.get("disposition")
    if disposition not in _ALLOWED_DISPOSITIONS:
        raise ValueError("invalid information-gap disposition")
    refs = raw.get("evidence_refs", [])
    if not isinstance(refs, list) or any(ref not in allowed_evidence_refs for ref in refs):
        raise ValueError("information-gap evidence is outside current retrieval evidence")
    ambiguities: list[WorkAmbiguityV1] = []
    for item in raw.get("ambiguities", []):
        if not isinstance(item, Mapping):
            raise ValueError("invalid ambiguity candidate")
        item_refs = item.get("evidence_refs", [])
        if not isinstance(item_refs, list) or any(
            ref not in allowed_evidence_refs for ref in item_refs
        ):
            raise ValueError("ambiguity evidence is outside current retrieval evidence")
        ambiguities.append(
            {
                "code": str(item.get("code", "")),
                "description": str(item.get("description", "")),
                "evidence_refs": list(item_refs),
            }
        )
    result: InformationGapAssessmentV1 = {
        "disposition": disposition,
        "ambiguities": ambiguities,
        "evidence_refs": list(refs),
    }  # type: ignore[typeddict-item]
    for key in ("needs", "question", "options", "reason_codes"):
        if key in raw:
            result[key] = raw[key]  # type: ignore[literal-required,typeddict-item]
    return result
