"""Canonical Work Analysis semantic operation: ``resolve_temporal_dependencies``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkRelationCandidateV1,
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

_TEMPORAL_KINDS = ("DEPENDS_ON", "DUE_AT", "RELATED_TO")
TEMPORAL_DEPENDENCIES_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="temporal-dependency-candidates-v1",
    json_schema={
        "type": "object",
        "required": ["relation_candidates"],
        "additionalProperties": False,
        "properties": {
            "relation_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "relation_id",
                        "kind",
                        "source_fact_id",
                        "target_fact_id",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "relation_id": {"type": "string", "minLength": 1},
                        "kind": {"enum": list(_TEMPORAL_KINDS)},
                        "source_fact_id": {"type": "string", "minLength": 1},
                        "target_fact_id": {"type": "string", "minLength": 1},
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


def resolve_temporal_dependencies(
    *,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    availability_results: list[dict[str, object]],
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    trace_context: ObservabilityContext,
    confirmation_response: dict[str, object] | None = None,
) -> list[WorkRelationCandidateV1]:
    """Produce temporal/order/dependency candidates without calendar arithmetic."""
    prompt_input: dict[str, object] = {
        "work_facts": [dict(fact) for fact in work_facts],
        "evidence": list(evidence),
        "availability_results": list(availability_results),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    fact_ids = {fact["fact_id"] for fact in work_facts}

    def validate(value: object) -> object:
        errors = validate_output_schema(value, TEMPORAL_DEPENDENCIES_OUTPUT_SCHEMA.json_schema)
        if errors:
            raise ValueError(f"invalid temporal relation candidate schema: {'; '.join(errors)}")
        seen: set[str] = set()
        root = cast(Mapping[str, object], value)
        for item in cast(list[Mapping[str, object]], root["relation_candidates"]):
            relation_id = cast(str, item["relation_id"])
            source = cast(str, item["source_fact_id"])
            target = cast(str, item["target_fact_id"])
            refs = cast(list[str], item["evidence_refs"])
            if (
                relation_id in seen
                or source == target
                or source not in fact_ids
                or target not in fact_ids
            ):
                raise ValueError("temporal relation identity or operands are invalid")
            if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
                raise ValueError("temporal relation evidence is outside current RetrievalResultV1")
            seen.add(relation_id)
        return value

    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=TEMPORAL_DEPENDENCIES_OUTPUT_SCHEMA,
        trace_context=trace_context,
        semantic_validate=validate,
    )
    root = cast(dict[str, object], validate(result.structured_output))
    return [
        cast(WorkRelationCandidateV1, dict(item))
        for item in cast(list[dict[str, object]], root["relation_candidates"])
    ]


__all__ = ["TEMPORAL_DEPENDENCIES_OUTPUT_SCHEMA", "resolve_temporal_dependencies"]
