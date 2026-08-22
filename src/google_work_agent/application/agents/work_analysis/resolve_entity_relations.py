"""Canonical Work Analysis semantic operation: resolve_entity_relations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import WorkAnalysisSemanticInputV1, WorkRelationCandidateV1
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import WorkFactV1


def resolve_entity_relations(*, semantic_input: WorkAnalysisSemanticInputV1, work_facts: Sequence[WorkFactV1], produce: Callable[[WorkAnalysisSemanticInputV1, Sequence[WorkFactV1]], object], allowed_evidence_refs: set[str]) -> list[WorkRelationCandidateV1]:
    """Produce non-temporal relation candidates; guarded relations remain candidates until deterministic validation."""
    raw = produce(semantic_input, work_facts)
    if not isinstance(raw, Mapping) or set(raw) != {"relation_candidates"} or not isinstance(raw["relation_candidates"], Sequence):
        raise ValueError("resolve_entity_relations requires exactly relation_candidates")
    fact_ids = {fact["fact_id"] for fact in work_facts}
    result: list[WorkRelationCandidateV1] = []
    for item in raw["relation_candidates"]:
        if not isinstance(item, Mapping) or set(item) != {"relation_type", "left_ref", "right_ref", "evidence_refs"}:
            raise ValueError("invalid relation candidate")
        relation_type = item["relation_type"]
        if relation_type in {"BEFORE", "AFTER", "OVERLAPS", "DEPENDS_ON"}:
            continue
        left, right, refs = item["left_ref"], item["right_ref"], item["evidence_refs"]
        if left not in fact_ids or right not in fact_ids or left == right:
            raise ValueError("relation operands must reference distinct same-invocation facts")
        if not isinstance(refs, list) or any(ref not in allowed_evidence_refs for ref in refs):
            raise ValueError("relation evidence is outside current retrieval evidence")
        result.append({"relation_type": str(relation_type), "left_ref": str(left), "right_ref": str(right), "evidence_refs": list(refs)})
    return result
