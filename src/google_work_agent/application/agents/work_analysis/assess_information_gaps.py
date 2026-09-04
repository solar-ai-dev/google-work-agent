"""Canonical Work Analysis semantic operation: ``assess_information_gaps``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
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
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

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
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
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
    output_schema = _bound_output_schema(allowed_evidence_refs)

    def validate(value: object) -> object:
        errors = validate_output_schema(value, output_schema.json_schema)
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

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    validated = cast(Mapping[str, object], validate(result.structured_output))
    return cast(InformationGapAssessmentV1, dict(validated))


def _bound_output_schema(allowed_evidence_refs: set[str]) -> OutputSchemaDefinition:
    """Express current evidence and disposition invariants at the repair boundary."""

    json_schema = cast(
        dict[str, object], deepcopy(ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA.json_schema)
    )
    properties = cast(dict[str, object], json_schema["properties"])
    evidence_item = {"type": "string", "enum": sorted(allowed_evidence_refs)}
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": evidence_item,
    }
    ambiguities = cast(dict[str, object], properties["ambiguities"])
    ambiguity = cast(dict[str, object], ambiguities["items"])
    ambiguity_properties = cast(dict[str, object], ambiguity["properties"])
    ambiguity_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": dict(evidence_item),
    }
    branches = [_disposition_schema(json_schema, disposition) for disposition in _DISPOSITIONS]
    return OutputSchemaDefinition(
        schema_version=ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA.schema_version,
        json_schema={"oneOf": branches},
    )


def _disposition_schema(
    base_schema: Mapping[str, object], disposition: str
) -> dict[str, object]:
    """Build one complete object branch for Ollama's structured-output grammar."""

    branch = cast(dict[str, object], deepcopy(base_schema))
    properties = cast(dict[str, object], branch["properties"])
    properties["disposition"] = {"const": disposition}
    retrieval_needs = cast(dict[str, object], properties["retrieval_needs"])
    retrieval_needs[
        "minItems" if disposition == "NEEDS_MORE_DATA" else "maxItems"
    ] = 1 if disposition == "NEEDS_MORE_DATA" else 0
    if disposition == "NEEDS_CONFIRMATION":
        required = cast(list[str], branch["required"])
        required.extend(["question", "reason_codes"])
        properties["question"] = {"type": "string", "minLength": 1}
        properties["reason_codes"] = {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        }
    return branch


__all__ = ["ASSESS_INFORMATION_GAPS_OUTPUT_SCHEMA", "assess_information_gaps"]
