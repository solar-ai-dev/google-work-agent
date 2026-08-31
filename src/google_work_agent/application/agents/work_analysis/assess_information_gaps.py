"""Canonical Work Analysis semantic operation: ``assess_information_gaps``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

_DISPOSITIONS = (
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
)

ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="information-gap-assessment-v1",
    json_schema={
        "type": "object",
        "required": ["disposition", "ambiguities", "retrieval_needs", "evidence_refs"],
        "additionalProperties": False,
        "properties": {
            "disposition": {"enum": list(_DISPOSITIONS)},
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "code",
                        "description",
                        "requires_confirmation",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "requires_confirmation": {"type": "boolean"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "retrieval_needs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["required_information", "reason_codes"],
                    "additionalProperties": False,
                    "properties": {
                        "required_information": {"type": "string", "minLength": 1},
                        "reason_codes": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "question": {"type": "string", "minLength": 1},
            "options": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def assess_information_gaps(
    *,
    request_intent: RequestIntentV2,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    trace_context: ObservabilityContext,
    confirmation_response: dict[str, object] | None = None,
) -> InformationGapAssessmentV1:
    """Identify only missing information and its legal workflow disposition."""

    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "work_facts": [dict(fact) for fact in work_facts],
        "evidence": list(evidence),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)

    def validate(value: object) -> object:
        errors = validate_output_schema(value, ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA.json_schema)
        if errors:
            raise ValueError(f"invalid information-gap schema: {'; '.join(errors)}")
        root = cast(Mapping[str, object], value)
        refs = cast(list[str], root["evidence_refs"])
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
            raise ValueError("information-gap evidence is outside current RetrievalResultV1")
        for ambiguity in cast(list[Mapping[str, object]], root["ambiguities"]):
            item_refs = cast(list[str], ambiguity["evidence_refs"])
            if len(item_refs) != len(set(item_refs)) or not set(item_refs).issubset(
                allowed_evidence_refs
            ):
                raise ValueError("ambiguity evidence is outside current RetrievalResultV1")
        disposition = root["disposition"]
        needs = cast(list[object], root["retrieval_needs"])
        reason_codes = root.get("reason_codes", [])
        if disposition == "NEEDS_MORE_DATA" and not needs:
            raise ValueError("NEEDS_MORE_DATA requires a RetrievalNeedV1")
        if disposition != "NEEDS_MORE_DATA" and needs:
            raise ValueError("retrieval needs are legal only for NEEDS_MORE_DATA")
        if disposition == "NEEDS_CONFIRMATION" and (
            not root.get("question") or not isinstance(reason_codes, list) or not reason_codes
        ):
            raise ValueError("NEEDS_CONFIRMATION requires question and reason_codes")
        return value

    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA,
        trace_context=trace_context,
        semantic_validate=validate,
    )
    validated = cast(Mapping[str, object], validate(result.structured_output))
    return cast(InformationGapAssessmentV1, dict(validated))


__all__ = ["ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA", "assess_information_gaps"]
