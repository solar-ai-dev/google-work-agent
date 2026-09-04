"""Complete analytical READ outlines from the current WorkAnalysis artifact."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)

_KOREAN_TEXT = re.compile(r"[가-힣]")


def complete_analysis_answer_outline(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    sections: Sequence[str],
    evidence_refs: Sequence[str],
    allowed_evidence_refs: Collection[str],
) -> AnswerOutlineV1:
    """Keep every current grounded work fact available to answer composition."""

    if request_intent.get("analysis_requirement") != "REQUIRED" or work_analysis is None:
        return {"sections": list(sections), "evidence_refs": list(evidence_refs)}
    facts = work_analysis.get("work_facts")
    if not isinstance(facts, list):
        return {"sections": list(sections), "evidence_refs": list(evidence_refs)}

    completed_sections = list(sections)
    completed_refs = list(evidence_refs)
    fact_heading = (
        "확인된 업무 사실" if _KOREAN_TEXT.search(user_request) else "Grounded work facts"
    )
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        subject = fact.get("subject")
        value = fact.get("value")
        if not isinstance(subject, str) or not subject or not isinstance(value, str) or not value:
            continue
        statement = f"{fact_heading} — {subject}: {value}"
        if statement not in completed_sections:
            completed_sections.append(statement)
        raw_refs = fact.get("evidence_refs")
        if isinstance(raw_refs, list):
            completed_refs.extend(
                ref for ref in raw_refs if isinstance(ref, str) and ref in allowed_evidence_refs
            )

    ambiguities = work_analysis.get("ambiguities")
    uncertainty_heading = "불확실성" if _KOREAN_TEXT.search(user_request) else "Uncertainty"
    if isinstance(ambiguities, list):
        for ambiguity in ambiguities:
            description = ambiguity.get("description") if isinstance(ambiguity, Mapping) else None
            if isinstance(description, str) and description:
                completed_sections.append(f"{uncertainty_heading} — {description}")
    return {
        "sections": list(dict.fromkeys(completed_sections)),
        "evidence_refs": list(dict.fromkeys(completed_refs)),
    }


__all__ = ["complete_analysis_answer_outline"]
