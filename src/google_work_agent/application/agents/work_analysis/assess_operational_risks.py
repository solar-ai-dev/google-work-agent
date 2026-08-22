"""Canonical Work Analysis semantic operation: assess_operational_risks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import OperationalRiskAssessmentV1, WorkAnalysisSemanticInputV1
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import WorkFactV1, WorkRelationV1, WorkRiskV1

_ALLOWED_SEVERITIES = frozenset({"INFO", "WARNING", "BLOCKING"})


def assess_operational_risks(*, semantic_input: WorkAnalysisSemanticInputV1, work_facts: Sequence[WorkFactV1], validated_relations: Sequence[WorkRelationV1], produce: Callable[[WorkAnalysisSemanticInputV1, Sequence[WorkFactV1], Sequence[WorkRelationV1]], object], allowed_evidence_refs: set[str]) -> OperationalRiskAssessmentV1:
    """Assess operational risks independently from information-gap disposition."""
    raw = produce(semantic_input, work_facts, validated_relations)
    if not isinstance(raw, Mapping) or set(raw) != {"risks", "evidence_refs"}:
        raise ValueError("operational-risk output must contain only risks and evidence_refs")
    refs = raw["evidence_refs"]
    if not isinstance(refs, list) or any(ref not in allowed_evidence_refs for ref in refs):
        raise ValueError("operational-risk evidence is outside current retrieval evidence")
    risks: list[WorkRiskV1] = []
    if not isinstance(raw["risks"], Sequence):
        raise ValueError("risks must be a sequence")
    for item in raw["risks"]:
        if not isinstance(item, Mapping) or set(item) != {"code", "severity", "description", "evidence_refs"}:
            raise ValueError("invalid WorkRiskV1 candidate")
        severity, item_refs = item["severity"], item["evidence_refs"]
        if severity not in _ALLOWED_SEVERITIES or not isinstance(item_refs, list) or any(ref not in allowed_evidence_refs for ref in item_refs):
            raise ValueError("invalid operational risk")
        risks.append({"code": str(item["code"]), "severity": severity, "description": str(item["description"]), "evidence_refs": list(item_refs)})  # type: ignore[typeddict-item]
    return {"risks": risks, "evidence_refs": list(refs)}
