"""Canonical Work Analysis semantic operation: ``assess_operational_risks``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    OperationalRiskAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
)
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

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
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    allowed_evidence_refs: set[str],
    trace_context: ObservabilityContext,
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

    def validate(value: object) -> object:
        errors = validate_output_schema(value, ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA.json_schema)
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

    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA,
        trace_context=trace_context,
        semantic_validate=validate,
    )
    validated = cast(Mapping[str, object], validate(result.structured_output))
    return cast(OperationalRiskAssessmentV1, dict(validated))


__all__ = ["ASSESS_OPERATIONAL_RISKS_OUTPUT_SCHEMA", "assess_operational_risks"]
