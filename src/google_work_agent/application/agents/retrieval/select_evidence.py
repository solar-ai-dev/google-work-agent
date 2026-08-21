"""Canonical Retrieval semantic operation: select_evidence."""

from __future__ import annotations

from typing import Literal, cast

from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    DEFAULT_CONTEXT_BUDGET,
    SourceSegment,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.contracts import (
    BudgetDecision,
    RunBudgetV1,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.workflows.failure_record import build_failure_record_v1
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceRoleDraftV2,
    EvidenceSelectionResultV2,
    RequestIntentV2,
)
from google_work_agent.ports import OutputSchemaDefinition, PromptReference


EVIDENCE_SELECTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="evidence-selection-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "evidence_drafts",
            "selected_segment_ids",
            "excluded_segment_ids",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "evidence_drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["segment_id", "role", "relevance_reason"],
                    "additionalProperties": False,
                    "properties": {
                        "segment_id": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["SUPPORTS", "CONTRADICTS", "CONTEXT"],
                        },
                        "relevance_reason": {"type": "string"},
                    },
                },
            },
            "selected_segment_ids": {"type": "array", "items": {"type": "string"}},
            "excluded_segment_ids": {"type": "array", "items": {"type": "string"}},
        },
    },
)


def select_evidence(
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    request_intent: RequestIntentV2,
    rag_candidates: list[RagCandidateV1],
    segments: list[SourceSegment],
    retry_budget: RunBudgetV1,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> tuple[EvidenceSelectionResultV2, RunBudgetV1]:
    """Select evidence only from the bounded ranked segments supplied by RAG."""
    projection = _ranked_segments_projection(rag_candidates, segments)
    candidate_ids = {candidate["segment_id"] for candidate in rag_candidates}
    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input={"request_intent": request_intent, "ranked_segments": projection},
        output_schema=EVIDENCE_SELECTION_OUTPUT_SCHEMA,
        trace_context=trace_context,
    )
    try:
        return (
            _validate_selection(
                result.structured_output,
                candidate_segment_ids=candidate_ids,
                context_budget=context_budget,
            ),
            retry_budget,
        )
    except ValueError as error:
        signature = build_semantic_failure_signature_v1(
            node_id="retrieval.select_evidence",
            failure_reason_codes=["EVIDENCE_SELECTION_SEMANTIC_INVALID"],
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            return _empty_selection(), decision["run_budget"]
        revision = llm_runtime.invoke_structured(
            prompt_ref=revision_prompt_ref,
            prompt_input={
                "base_projection": {
                    "request_intent": request_intent,
                    "ranked_segments": projection,
                },
                "candidate_output": result.structured_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code="EVIDENCE_SELECTION_SEMANTIC_INVALID",
                    failure_origin="RETRIEVAL_RESULT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=[
                        "$.selected_segment_ids",
                        "$.evidence_drafts",
                        "$.excluded_segment_ids",
                    ],
                    failure_context_ids=[str(error)],
                ),
            },
            output_schema=EVIDENCE_SELECTION_OUTPUT_SCHEMA,
            trace_context=trace_context,
        )
        try:
            return (
                _validate_selection(
                    revision.structured_output,
                    candidate_segment_ids=candidate_ids,
                    context_budget=context_budget,
                ),
                decision["run_budget"],
            )
        except ValueError:
            return _empty_selection(), decision["run_budget"]


def _ranked_segments_projection(
    candidates: list[RagCandidateV1], segments: list[SourceSegment]
) -> list[dict[str, object]]:
    by_id = {segment.segment_id: segment for segment in segments}
    result: list[dict[str, object]] = []
    for candidate in candidates:
        segment = by_id.get(candidate["segment_id"])
        if segment is None:
            raise ValueError(f"RAG_SEGMENT_REFERENCE_INVALID: {candidate['segment_id']}")
        result.append(
            {
                "segment_id": candidate["segment_id"],
                "resource_ref": candidate["resource_ref"],
                "excerpt": segment.text,
                "retrieval_score": candidate["retrieval_score"],
                "reason_codes": list(candidate["reason_codes"]),
                "trust_class": "UNTRUSTED_SOURCE_CONTENT",
                "content_role": "DATA_ONLY",
            }
        )
    return result


def _validate_selection(
    value: object,
    *,
    candidate_segment_ids: set[str],
    context_budget: ContextBudget,
) -> EvidenceSelectionResultV2:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "evidence_drafts",
        "selected_segment_ids",
        "excluded_segment_ids",
    }:
        raise ValueError("invalid evidence selection envelope")
    if value["schema_version"] != 2:
        raise ValueError("schema_version must be 2")
    selected = _string_list(value["selected_segment_ids"], "selected_segment_ids")
    excluded = _string_list(value["excluded_segment_ids"], "excluded_segment_ids")
    if len(selected) != len(set(selected)) or len(excluded) != len(set(excluded)):
        raise ValueError("segment ids must be unique")
    if (set(selected) | set(excluded)) - candidate_segment_ids:
        raise ValueError("selection references a segment outside ranked candidates")
    if set(selected) & set(excluded):
        raise ValueError("segment cannot be selected and excluded")
    raw_drafts = value["evidence_drafts"]
    if not isinstance(raw_drafts, list):
        raise ValueError("evidence_drafts must be list")
    drafts: list[EvidenceRoleDraftV2] = []
    for raw in raw_drafts:
        if not isinstance(raw, dict) or set(raw) != {"segment_id", "role", "relevance_reason"}:
            raise ValueError("invalid evidence draft")
        segment_id = raw.get("segment_id")
        role = raw.get("role")
        reason = raw.get("relevance_reason")
        if segment_id not in set(selected):
            raise ValueError("evidence references unselected segment")
        if role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}:
            raise ValueError("invalid evidence role")
        if not isinstance(reason, str):
            raise ValueError("relevance_reason must be string")
        drafts.append(
            {
                "segment_id": str(segment_id),
                "role": cast(Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"], role),
                "relevance_reason": reason,
            }
        )
    return {
        "schema_version": 2,
        "evidence_drafts": drafts[: context_budget.max_evidence],
        "selected_segment_ids": selected,
        "excluded_segment_ids": excluded,
    }


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be list[str]")
    return list(value)


def _empty_selection() -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
    }
