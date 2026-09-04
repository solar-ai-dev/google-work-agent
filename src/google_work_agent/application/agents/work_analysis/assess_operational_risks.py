"""Canonical Work Analysis semantic operation: ``assess_operational_risks``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    OperationalRiskAssessmentV1,
)
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

_RISK_KINDS = (
    "SCHEDULE_CONFLICT",
    "DEADLINE_RISK",
    "DUPLICATE_RISK",
    "MISSING_INFORMATION",
    "OTHER",
)

ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="operational-risk-assessment-v1",
    json_schema={
        "type": "object",
        "required": [
            "risks",
            "action_necessity_candidate",
            "action_necessity_reason",
            "evidence_refs",
        ],
        "additionalProperties": False,
        "properties": {
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "severity", "description", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"enum": list(_RISK_KINDS)},
                        "severity": {"enum": ["LOW", "MEDIUM", "HIGH"]},
                        "description": {"type": "string", "minLength": 1},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "action_necessity_candidate": {"enum": ["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]},
            "action_necessity_reason": {"type": ["string", "null"]},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def assess_operational_risks(
    *,
    request_intent: RequestIntentV2,
    work_facts: Sequence[WorkFactV1],
    validated_relations: Sequence[WorkRelationV1],
    evidence: list[dict[str, object]],
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    requested_mode: RequestedModeV1,
    policy_summary: dict[str, object] | None = None,
    confirmation_response: dict[str, object] | None = None,
) -> OperationalRiskAssessmentV1:
    """Propose risks/action necessity without assuming Policy or Approval authority."""

    prompt_input: dict[str, object] = {
        "request_intent": dict(request_intent),
        "work_facts": [dict(fact) for fact in work_facts],
        "validated_relations": [dict(relation) for relation in validated_relations],
        "evidence": list(evidence),
    }
    if policy_summary is not None:
        prompt_input["policy_summary"] = dict(policy_summary)
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    output_schema = _bound_output_schema(allowed_evidence_refs)

    def validate(value: object) -> object:
        errors = validate_output_schema(value, output_schema.json_schema)
        if errors:
            raise ValueError(f"invalid operational-risk schema: {'; '.join(errors)}")
        root = cast(Mapping[str, object], value)
        refs = cast(list[str], root["evidence_refs"])
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_evidence_refs):
            raise ValueError("operational-risk evidence is outside current RetrievalResultV1")
        for risk in cast(list[Mapping[str, object]], root["risks"]):
            item_refs = cast(list[str], risk["evidence_refs"])
            if len(item_refs) != len(set(item_refs)) or not set(item_refs).issubset(
                allowed_evidence_refs
            ):
                raise ValueError("risk evidence is outside current RetrievalResultV1")
        reason = root["action_necessity_reason"]
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("action_necessity_reason must be non-empty or null")
        return value

    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        output_schema,
    )
    validated = cast(Mapping[str, object], validate(result.structured_output))
    return cast(OperationalRiskAssessmentV1, dict(validated))


def _bound_output_schema(allowed_evidence_refs: set[str]) -> OutputSchemaDefinition:
    """Bind every risk citation to the current durable Retrieval evidence."""

    json_schema = deepcopy(ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA.json_schema)
    properties = cast(dict[str, object], json_schema["properties"])
    evidence_ref_schema = {
        "type": "string",
        "enum": sorted(allowed_evidence_refs),
    }
    properties["evidence_refs"] = {
        "type": "array",
        "uniqueItems": True,
        "items": evidence_ref_schema,
    }
    risks = cast(dict[str, object], properties["risks"])
    risk_item = cast(dict[str, object], risks["items"])
    risk_properties = cast(dict[str, object], risk_item["properties"])
    risk_properties["evidence_refs"] = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": dict(evidence_ref_schema),
    }
    return OutputSchemaDefinition(
        schema_version=ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


__all__ = ["ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA", "assess_operational_risks"]
