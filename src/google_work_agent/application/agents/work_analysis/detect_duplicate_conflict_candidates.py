"""Canonical Work Analysis semantic operation: detect_duplicate_conflict_candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkAnalysisSemanticInputV1,
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)

_GUARDED_TYPES = frozenset({"DUPLICATES", "CONFLICTS_WITH"})


def detect_duplicate_conflict_candidates(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    work_facts: Sequence[WorkFactV1],
    produce: Callable[[WorkAnalysisSemanticInputV1, Sequence[WorkFactV1]], object],
    allowed_evidence_refs: set[str],
) -> list[WorkRelationCandidateV1]:
    """Produce guarded duplicate/conflict candidates; deterministic validation owns promotion."""
    raw = produce(semantic_input, work_facts)
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"relation_candidates"}
        or not isinstance(raw["relation_candidates"], Sequence)
    ):
        raise ValueError(
            "detect_duplicate_conflict_candidates requires exactly relation_candidates"
        )
    fact_ids = {fact["fact_id"] for fact in work_facts}
    result: list[WorkRelationCandidateV1] = []
    for item in raw["relation_candidates"]:
        if not isinstance(item, Mapping) or item.get("relation_type") not in _GUARDED_TYPES:
            continue
        left, right, refs = item.get("left_ref"), item.get("right_ref"), item.get("evidence_refs")
        if left not in fact_ids or right not in fact_ids or left == right:
            raise ValueError("guarded relation operands are invalid")
        if not isinstance(refs, list) or any(ref not in allowed_evidence_refs for ref in refs):
            raise ValueError("guarded relation evidence is outside current retrieval evidence")
        result.append(
            {
                "relation_type": str(item["relation_type"]),
                "left_ref": str(left),
                "right_ref": str(right),
                "evidence_refs": list(refs),
            }
        )
    return result
