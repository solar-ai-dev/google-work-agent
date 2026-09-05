"""Compose the user-facing answer through the canonical Planning Prompt slot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.normalize_generated_answer_prose import (
    normalize_generated_answer_prose,
)
from google_work_agent.application.agents.planning.project_empty_read_answer import (
    project_empty_read_answer,
)
from google_work_agent.application.agents.planning.project_gmail_decision_read_answer import (
    project_gmail_decision_read_answer,
)
from google_work_agent.application.agents.planning.project_gmail_read_planning import (
    project_gmail_read_planning,
)
from google_work_agent.application.agents.planning.project_gmail_security_read_answer import (
    project_gmail_security_read_answer,
)
from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.application.agents.planning.sanitize_user_visible_answer import (
    sanitize_user_visible_answer,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.compose_answer"
MAX_USER_VISIBLE_ANSWER_CHARS = 2_400

ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-answer-draft-v2",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "answer", "evidence_refs"],
        "properties": {
            "schema_version": {"const": 2},
            "answer": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_USER_VISIBLE_ANSWER_CHARS,
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def answer_draft_output_schema(allowed_evidence_refs: Sequence[str]) -> OutputSchemaDefinition:
    """Bind answer citations to the evidence approved by the current outline."""

    json_schema = deepcopy(ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "maxItems": len(set(allowed_evidence_refs)),
        "items": {"type": "string", "enum": sorted(set(allowed_evidence_refs))},
    }
    return OutputSchemaDefinition(
        schema_version=ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


def compose_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    answer_outline: AnswerOutlineV1,
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
    confirmation_response: Mapping[str, object] | None = None,
    retrieval_result: Mapping[str, object] | None = None,
) -> AnswerDraftCandidateV2:
    if not user_request.strip():
        raise ValueError("user_request is required")
    approved_refs = set(answer_outline["evidence_refs"])
    approved_evidence = [
        dict(item) for item in evidence if _evidence_ref(item) in approved_refs
    ]
    prompt_input: dict[str, object] = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "answer_outline": dict(answer_outline),
        "evidence": approved_evidence,
    }
    gmail_projection = project_gmail_read_planning(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if work_analysis is not None and gmail_projection is None:
        prompt_input["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    task_projection = project_task_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if task_projection is not None:
        if not set(task_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("task read answer references evidence outside its approved outline")
        return task_projection.draft
    decision_projection = project_gmail_decision_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if decision_projection is not None:
        if not set(decision_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("Gmail decision answer references evidence outside its outline")
        return decision_projection.draft
    security_projection = project_gmail_security_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if security_projection is not None:
        if not set(security_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("Gmail security answer references evidence outside its outline")
        return security_projection.draft
    empty_projection = project_empty_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        retrieval_result=retrieval_result,
        evidence=evidence,
    )
    if empty_projection is not None:
        return empty_projection.draft
    candidate = invoke(PROMPT_ID, prompt_input)
    schema_version = candidate.get("schema_version")
    answer = candidate.get("answer")
    refs = candidate.get("evidence_refs")
    if schema_version != 2:
        raise ValueError("compose_answer output requires schema_version 2")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("compose_answer output requires answer")
    normalized_answer = normalize_generated_answer_prose(answer)
    if len(normalized_answer) > MAX_USER_VISIBLE_ANSWER_CHARS:
        raise ValueError("compose_answer output exceeds the user-visible answer limit")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("compose_answer output requires evidence_refs")
    allowed = set(answer_outline["evidence_refs"])
    if not set(refs).issubset(allowed):
        raise ValueError("compose_answer referenced evidence outside its projection")
    if len(refs) != len(set(refs)):
        raise ValueError("compose_answer output contains duplicate evidence_refs")
    visible_answer = sanitize_user_visible_answer(
        normalized_answer,
        internal_refs=[*allowed, *refs],
        user_request=user_request,
        source_texts=[
            excerpt
            for item in approved_evidence
            if isinstance((excerpt := item.get("excerpt")), str)
        ],
    )
    return {"schema_version": 2, "answer": visible_answer, "evidence_refs": list(refs)}


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


__all__ = [
    "ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA",
    "MAX_USER_VISIBLE_ANSWER_CHARS",
    "answer_draft_output_schema",
    "compose_answer",
]
