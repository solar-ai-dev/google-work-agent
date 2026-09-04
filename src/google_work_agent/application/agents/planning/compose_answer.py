"""Compose the user-facing answer through the canonical Planning Prompt slot."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.compose_answer"

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
) -> AnswerDraftCandidateV2:
    if not user_request.strip():
        raise ValueError("user_request is required")
    prompt_input: dict[str, object] = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "answer_outline": dict(answer_outline),
        "evidence": [dict(item) for item in evidence],
    }
    if work_analysis is not None:
        prompt_input["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    task_projection = project_task_read_answer(
        user_request=user_request,
        request_intent=request_intent,
        evidence=evidence,
    )
    if task_projection is not None:
        approved_refs = set(answer_outline["evidence_refs"])
        if not set(task_projection.draft["evidence_refs"]).issubset(approved_refs):
            raise ValueError("task read answer references evidence outside its approved outline")
        return task_projection.draft
    candidate = invoke(PROMPT_ID, prompt_input)
    schema_version = candidate.get("schema_version")
    answer = candidate.get("answer")
    refs = candidate.get("evidence_refs")
    if schema_version != 2:
        raise ValueError("compose_answer output requires schema_version 2")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("compose_answer output requires answer")
    normalized_answer = answer.strip()
    if _is_serialized_container(normalized_answer):
        raise ValueError("compose_answer answer must be user-visible prose")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("compose_answer output requires evidence_refs")
    allowed = set(answer_outline["evidence_refs"])
    if not set(refs).issubset(allowed):
        raise ValueError("compose_answer referenced evidence outside its projection")
    if len(refs) != len(set(refs)):
        raise ValueError("compose_answer output contains duplicate evidence_refs")
    return {"schema_version": 2, "answer": normalized_answer, "evidence_refs": list(refs)}


def _is_serialized_container(answer: str) -> bool:
    stripped = answer.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


__all__ = [
    "ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA",
    "answer_draft_output_schema",
    "compose_answer",
]
