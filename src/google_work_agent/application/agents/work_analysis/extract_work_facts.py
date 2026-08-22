"""Canonical Work Analysis semantic operation: extract_work_facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import WorkAnalysisSemanticInputV1
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import WorkFactV1


def extract_work_facts(*, semantic_input: WorkAnalysisSemanticInputV1, produce: Callable[[WorkAnalysisSemanticInputV1], object], allowed_evidence_refs: set[str]) -> list[WorkFactV1]:
    """Produce and validate same-invocation work facts; evidence refs are fail-closed."""
    raw = produce(semantic_input)
    if not isinstance(raw, Mapping) or set(raw) != {"fact_candidates"} or not isinstance(raw["fact_candidates"], Sequence):
        raise ValueError("extract_work_facts requires exactly fact_candidates")
    result: list[WorkFactV1] = []
    seen: set[str] = set()
    for item in raw["fact_candidates"]:
        if not isinstance(item, Mapping) or set(item) != {"fact_id", "fact_type", "value", "evidence_refs"}:
            raise ValueError("invalid WorkFactV1 candidate")
        fact_id, fact_type = item["fact_id"], item["fact_type"]
        refs = item["evidence_refs"]
        if not isinstance(fact_id, str) or not fact_id or fact_id in seen or not isinstance(fact_type, str) or not fact_type:
            raise ValueError("work fact identity is invalid")
        if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in allowed_evidence_refs for ref in refs):
            raise ValueError("work fact references evidence outside the current retrieval result")
        value = item["value"]
        if not isinstance(value, (str, list)):
            raise ValueError("work fact value is invalid")
        seen.add(fact_id)
        result.append({"fact_id": fact_id, "fact_type": fact_type, "value": value, "evidence_refs": list(refs)})
    return result
