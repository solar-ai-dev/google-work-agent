"""Canonical Work Analysis semantic operation: ``resolve_entity_relations``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

_ENTITY_KINDS = ("ASSIGNED_TO", "RELATED_TO")
ENTITY_RELATIONS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="entity-relation-candidates-v1",
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
                        "kind": {"enum": list(_ENTITY_KINDS)},
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


def resolve_entity_relations(
    *,
    work_facts: Sequence[WorkFactV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> list[WorkRelationV1]:
    """Produce only entity/ownership/reference candidates; never final relations."""

    prompt_input: dict[str, object] = {
        "work_facts": [dict(fact) for fact in work_facts],
        "evidence": list(evidence),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    fact_ids = {fact["fact_id"] for fact in work_facts}
    output_schema = _bound_output_schema(fact_ids, allowed_evidence_refs)

    def validate(value: object) -> object:
        errors = validate_output_schema(value, output_schema.json_schema)
        if errors:
            raise ValueError(f"invalid entity relation candidate schema: {'; '.join(errors)}")
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
                raise ValueError("entity relation identity or operands are invalid")
            if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
                raise ValueError("entity relation evidence is outside current RetrievalResultV1")
            seen.add(relation_id)
        return value

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    root = cast(dict[str, object], validate(result.structured_output))
    return [
        cast(WorkRelationV1, dict(item))
        for item in cast(list[dict[str, object]], root["relation_candidates"])
    ]


def _bound_output_schema(
    fact_ids: set[str], allowed_evidence_refs: set[str]
) -> OutputSchemaDefinition:
    """Bind LLM-generated references to the current validated artifact identities."""

    json_schema = deepcopy(ENTITY_RELATIONS_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    candidates = cast(dict[str, object], properties["relation_candidates"])
    item = cast(dict[str, object], candidates["items"])
    item_properties = cast(dict[str, object], item["properties"])
    fact_id_schema = {"type": "string", "enum": sorted(fact_ids)}
    item_properties["source_fact_id"] = fact_id_schema
    item_properties["target_fact_id"] = dict(fact_id_schema)
    item_properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": sorted(allowed_evidence_refs)},
    }
    return OutputSchemaDefinition(
        schema_version=ENTITY_RELATIONS_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


__all__ = ["ENTITY_RELATIONS_OUTPUT_SCHEMA", "resolve_entity_relations"]
