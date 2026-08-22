"""Build the bounded answer outline consumed by compose_answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)


def outline_answer(
    *,
    request_intent: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
) -> AnswerOutlineV1:
    """Deterministically expose answer dimensions without inventing facts."""
    goal = request_intent.get("goal") or request_intent.get("canonical_goal")
    sections = [str(goal)] if isinstance(goal, str) and goal.strip() else ["direct_answer"]
    if work_analysis:
        for key in ("missing_information", "operational_risks"):
            value = work_analysis.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
                sections.append(key)
    evidence_refs: list[str] = []
    for item in evidence:
        ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if isinstance(ref, str) and ref and ref not in evidence_refs:
            evidence_refs.append(ref)
    return {"sections": sections, "evidence_refs": evidence_refs}
