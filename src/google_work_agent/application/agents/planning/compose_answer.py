"""Compose the user-facing answer through the canonical Planning Prompt slot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
    PlanningSemanticInvoker,
)

PROMPT_ID = "planning.compose_answer"


def compose_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    answer_outline: AnswerOutlineV1,
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
    confirmation_response: Mapping[str, object] | None = None,
) -> AnswerDraftCandidateV2:
    if not user_request.strip():
        raise ValueError("user_request is required")
    prompt_input: dict[str, object] = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "answer_outline": dict(answer_outline),
        "work_analysis": dict(work_analysis) if work_analysis is not None else None,
        "evidence": [dict(item) for item in evidence],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    candidate = invoke(PROMPT_ID, prompt_input)
    answer = candidate.get("answer")
    refs = candidate.get("evidence_refs")
    if not isinstance(answer, str):
        raise ValueError("compose_answer output requires answer")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("compose_answer output requires evidence_refs")
    allowed = set(answer_outline["evidence_refs"])
    if not set(refs).issubset(allowed):
        raise ValueError("compose_answer referenced evidence outside its projection")
    return {"answer": answer, "evidence_refs": list(refs)}
