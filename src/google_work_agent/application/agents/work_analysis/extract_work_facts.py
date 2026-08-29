"""Canonical Work Analysis semantic operation: ``extract_work_facts``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkAnalysisSemanticInputV1,
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

_FACT_KINDS = (
    "TASK",
    "EVENT",
    "PERSON",
    "DATE",
    "TIME",
    "DEADLINE",
    "STATUS",
    "RESOURCE",
    "TEXT_CLAIM",
    "OTHER",
)
EXTRACT_WORK_FACTS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-fact-candidates-v1",
    json_schema={
        "type": "object",
        "required": ["fact_candidates"],
        "additionalProperties": False,
        "properties": {
            "fact_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "fact_id",
                        "kind",
                        "subject",
                        "value",
                        "derivation",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "fact_id": {"type": "string", "minLength": 1},
                        "kind": {"enum": list(_FACT_KINDS)},
                        "subject": {"type": "string", "minLength": 1},
                        "value": {"type": "string", "minLength": 1},
                        "derivation": {"enum": ["EXPLICIT", "DERIVED"]},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
)


def extract_work_facts(
    *,
    semantic_input: WorkAnalysisSemanticInputV1,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    trace_context: ObservabilityContext,
) -> list[WorkFactV1]:
    """Extract only evidence-grounded facts from the current Retrieval revision."""

    prompt_input: dict[str, object] = {
        "user_request": semantic_input["user_request"],
        "request_intent": semantic_input["request_intent"],
        "evidence": list(semantic_input["evidence"]),
    }
    if "availability_results" in semantic_input:
        prompt_input["availability_results"] = list(semantic_input["availability_results"])
    if "confirmation_response" in semantic_input:
        prompt_input["confirmation_response"] = dict(semantic_input["confirmation_response"])

    def validate(value: object) -> object:
        errors = validate_output_schema(value, EXTRACT_WORK_FACTS_OUTPUT_SCHEMA.json_schema)
        if errors:
            raise ValueError(f"invalid WorkFactV1 candidate schema: {'; '.join(errors)}")
        root = cast(Mapping[str, object], value)
        seen: set[str] = set()
        for item in cast(list[Mapping[str, object]], root["fact_candidates"]):
            fact_id = cast(str, item["fact_id"])
            refs = cast(list[str], item["evidence_refs"])
            if fact_id in seen:
                raise ValueError("duplicate WorkFactV1.fact_id")
            if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
                raise ValueError("work fact references evidence outside current RetrievalResultV1")
            seen.add(fact_id)
        return value

    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=EXTRACT_WORK_FACTS_OUTPUT_SCHEMA,
        trace_context=trace_context,
        semantic_validate=validate,
    )
    root = cast(dict[str, object], validate(result.structured_output))
    return [
        cast(WorkFactV1, dict(item))
        for item in cast(list[dict[str, object]], root["fact_candidates"])
    ]


__all__ = ["EXTRACT_WORK_FACTS_OUTPUT_SCHEMA", "extract_work_facts"]
