"""Build the bounded answer outline through its canonical Product Prompt."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
    PlanningAnswerConfirmationV1,
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.outline_answer"

ANSWER_OUTLINE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-answer-outline-v1",
    json_schema={
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["sections", "evidence_refs"],
                "properties": {
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["disposition", "question", "options", "reason_codes"],
                "properties": {
                    "disposition": {"const": "NEEDS_CONFIRMATION"},
                    "question": {"type": "string", "minLength": 1},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "reason_codes": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        ]
    },
)


def answer_outline_output_schema(
    allowed_evidence_refs: Sequence[str],
    *,
    confirmation_allowed: bool,
) -> OutputSchemaDefinition:
    """Bind citations and confirmation eligibility to the current typed intent."""

    json_schema = cast(dict[str, object], deepcopy(ANSWER_OUTLINE_OUTPUT_SCHEMA.json_schema))
    branches = cast(list[object], json_schema["oneOf"])
    answer_schema = cast(dict[str, object], branches[0])
    properties = cast(dict[str, object], answer_schema["properties"])
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(set(allowed_evidence_refs))},
    }
    if not confirmation_allowed:
        json_schema["oneOf"] = [answer_schema]
    return OutputSchemaDefinition(
        schema_version=ANSWER_OUTLINE_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


def outline_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
    confirmation_response: Mapping[str, object] | None = None,
) -> AnswerOutlineV1 | PlanningAnswerConfirmationV1:
    """Return an evidence-bounded outline without assuming policy or action authority."""
    if not user_request.strip():
        raise ValueError("user_request is required")
    allowed_refs: set[str] = set()
    for item in evidence:
        ref = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
        if isinstance(ref, str) and ref:
            allowed_refs.add(ref)
    prompt_input: dict[str, object] = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
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
        return task_projection.outline
    candidate = invoke(PROMPT_ID, prompt_input)
    if candidate.get("disposition") == "NEEDS_CONFIRMATION":
        ambiguity = request_intent.get("ambiguity")
        if not isinstance(ambiguity, Mapping) or ambiguity.get("requires_confirmation") is not True:
            raise ValueError("outline_answer confirmation is not permitted for actionable intent")
        question = candidate.get("question")
        options = candidate.get("options")
        reason_codes = candidate.get("reason_codes")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("outline_answer confirmation requires question")
        if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
            raise ValueError("outline_answer confirmation requires options")
        if (
            not isinstance(reason_codes, list)
            or not reason_codes
            or not all(isinstance(item, str) and item for item in reason_codes)
        ):
            raise ValueError("outline_answer confirmation requires reason_codes")
        return {
            "disposition": "NEEDS_CONFIRMATION",
            "question": question,
            "options": list(options),
            "reason_codes": list(reason_codes),
        }
    sections = candidate.get("sections")
    refs = candidate.get("evidence_refs")
    if (
        not isinstance(sections, list)
        or not sections
        or not all(isinstance(item, str) and item.strip() for item in sections)
    ):
        raise ValueError("outline_answer output requires non-empty sections")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("outline_answer output requires evidence_refs")
    if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_refs):
        raise ValueError("outline_answer referenced evidence outside its projection")
    return {"sections": list(sections), "evidence_refs": list(refs)}


__all__ = [
    "ANSWER_OUTLINE_OUTPUT_SCHEMA",
    "answer_outline_output_schema",
    "outline_answer",
]
