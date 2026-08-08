"""Context retrieval workflow node implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.api_acquisition import AcquisitionResultV1
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    ContextResult,
    WorkflowPhase,
    validate_additional_acquisition_request_v1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.workflows.request_understanding import (
    ClarificationQuestionV1,
    RequestIntentV1,
    build_clarification_question_v1,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]
ContextStatusValue = Literal[
    "SUFFICIENT",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "PARTIAL",
    "BLOCKED",
]


class EvidenceDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    evidence_id: str
    resource_handle: str
    segment_id: str
    kind: str
    excerpt: str
    locator: dict[str, object] | None
    reason_codes: list[str]


class ContextBundleV1(TypedDict):
    schema_version: Required[Literal[1]]
    resource_refs: list[dict[str, object]]
    segment_refs: list[dict[str, object]]
    evidence_refs: list[str]
    normalized_context: list[dict[str, object]]
    missing_information: list[str]
    ambiguity: dict[str, object] | None


class ContextRetrievalResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: ContextStatusValue
    context_bundle: ContextBundleV1
    evidence_drafts: list[EvidenceDraftV1]
    selected_segment_ids: list[str]
    excluded_resource_handles: list[str]
    missing_slots: list[str]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    sufficiency: dict[str, object]
    llm_provider_result: NotRequired[dict[str, object]]


class EvidenceSelectionOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["SELECTED", "PARTIAL", "BLOCKED"]
    selected_segment_ids: list[str]
    evidence_drafts: list[EvidenceDraftV1]
    excluded_resource_handles: list[str]
    missing_information: list[str]
    ambiguity: dict[str, object] | None


class SufficiencyOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: ContextStatusValue
    sufficiency: dict[str, object]
    missing_slots: list[str]
    ambiguity: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_segments: int = 24
    max_segment_chars: int = 1200
    max_evidence: int = 12
    max_excerpt_chars: int = 1200
    max_normalized_context_items: int = 12


DEFAULT_CONTEXT_BUDGET = ContextBudget()


@dataclass(frozen=True, slots=True)
class _SourceSegment:
    segment_id: str
    resource_handle: str
    source: str
    resource_type: str
    resource_id: str
    parent_id: str | None
    version: str | None
    locator: dict[str, object]
    text: str


CONTEXT_RETRIEVAL_SCHEMA_VERSION = 1
CONTEXT_BUNDLE_SCHEMA_VERSION = 1
EVIDENCE_DRAFT_SCHEMA_VERSION = 1
EVIDENCE_SELECTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="evidence-selection-v1",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "result",
            "selected_segment_ids",
            "evidence_drafts",
            "excluded_resource_handles",
            "missing_information",
            "ambiguity",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "result": {"type": "string", "enum": ["SELECTED", "PARTIAL", "BLOCKED"]},
            "selected_segment_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_drafts": {"type": "array", "items": {"type": "object"}},
            "excluded_resource_handles": {"type": "array", "items": {"type": "string"}},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "ambiguity": {},
        },
    },
)
SUFFICIENCY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="context-sufficiency-v1",
    json_schema={
        "type": "object",
        "required": ["schema_version", "status", "sufficiency", "missing_slots", "ambiguity"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "status": {
                "type": "string",
                "enum": [
                    "SUFFICIENT",
                    "NEEDS_MORE_DATA",
                    "NEEDS_CONFIRMATION",
                    "PARTIAL",
                    "BLOCKED",
                ],
            },
            "sufficiency": {"type": "object"},
            "missing_slots": {"type": "array", "items": {"type": "string"}},
            "ambiguity": {},
        },
    },
)

_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}
_SELECTION_RESULT_VALUES = {"SELECTED", "PARTIAL", "BLOCKED"}
_TEXT_KEYS = (
    "title",
    "subject",
    "summary",
    "snippet",
    "body",
    "text",
    "description",
    "notes",
)


class ContextRetrievalValidationError(ValueError):
    """Raised when context retrieval structured output is invalid."""


class ContextRetrievalAgent:
    """Build a minimal context bundle from Stage 5 acquisition output."""

    def __init__(
        self,
        *,
        llm_runtime: LLMRuntimeService,
        select_prompt_ref: PromptReference | None = None,
        sufficiency_prompt_ref: PromptReference | None = None,
        context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._select_prompt_ref = (
            select_prompt_ref or load_context_select_evidence_prompt_reference()
        )
        self._sufficiency_prompt_ref = (
            sufficiency_prompt_ref or load_context_assess_sufficiency_prompt_reference()
        )
        self._context_budget = context_budget

    def retrieve(
        self,
        *,
        request_intent: RequestIntentV1,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
    ) -> ContextRetrievalResultV1:
        segments = _segments_from_acquisition(acquisition_result, self._context_budget)
        selection_result = self._select_evidence(
            request_intent=request_intent,
            acquisition_result=acquisition_result,
            request=request,
            segments=segments,
        )
        selected_segments = _selected_segments(
            selection_result["selected_segment_ids"],
            segments=segments,
        )
        evidence_drafts = _deduplicate_evidence(selection_result["evidence_drafts"])
        _validate_evidence_references(evidence_drafts, selected_segments=selected_segments)
        draft_bundle = _context_bundle(
            selected_segments=selected_segments,
            evidence_drafts=evidence_drafts,
            missing_information=selection_result["missing_information"],
            ambiguity=selection_result["ambiguity"],
            context_budget=self._context_budget,
        )
        sufficiency_result, llm_provider_result = self._assess_sufficiency(
            request_intent=request_intent,
            acquisition_result=acquisition_result,
            request=request,
            context_bundle=draft_bundle,
            evidence_drafts=evidence_drafts,
        )
        context_bundle = _context_bundle(
            selected_segments=selected_segments,
            evidence_drafts=evidence_drafts,
            missing_information=sufficiency_result["missing_slots"]
            or selection_result["missing_information"],
            ambiguity=sufficiency_result["ambiguity"] or selection_result["ambiguity"],
            context_budget=self._context_budget,
        )
        return {
            "schema_version": 1,
            "status": sufficiency_result["status"],
            "context_bundle": context_bundle,
            "evidence_drafts": evidence_drafts,
            "selected_segment_ids": list(selection_result["selected_segment_ids"]),
            "excluded_resource_handles": list(selection_result["excluded_resource_handles"]),
            "missing_slots": list(sufficiency_result["missing_slots"]),
            "additional_acquisition_request": _build_additional_acquisition_request(
                status=sufficiency_result["status"],
                missing_slots=sufficiency_result["missing_slots"],
                context_bundle=context_bundle,
            ),
            "sufficiency": dict(sufficiency_result["sufficiency"]),
            "llm_provider_result": llm_provider_result,
        }

    def build_state_update(self, result: ContextRetrievalResultV1) -> JsonObject:
        phase = (
            WorkflowPhase.WORK_ANALYSIS
            if ContextResult(result["status"]) is ContextResult.SUFFICIENT
            else WorkflowPhase.CONTEXT_EVALUATION
        )
        return {
            "context_result": result,
            "workflow_phase": phase.value,
            "trace_context": {
                "context_result": result["status"],
                "selected_segment_count": len(result["selected_segment_ids"]),
                "evidence_count": len(result["evidence_drafts"]),
                "missing_slots": list(result["missing_slots"]),
            },
        }

    def _select_evidence(
        self,
        *,
        request_intent: RequestIntentV1,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
        segments: list[_SourceSegment],
    ) -> EvidenceSelectionOutputV1:
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_prompt_ref,
            prompt_input={
                "request_intent": request_intent,
                "acquisition_status": acquisition_result["status"],
                "acquisition_missing_slots": list(acquisition_result["missing_slots"]),
                "source_content_is_untrusted": True,
                "segments": [_segment_prompt_projection(segment) for segment in segments],
                "context_budget": _budget_projection(self._context_budget),
            },
            output_schema=EVIDENCE_SELECTION_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:context.select_evidence",
            ),
        )
        return validate_evidence_selection_output_v1(
            llm_result.structured_output,
            segments=segments,
            context_budget=self._context_budget,
        )

    def _assess_sufficiency(
        self,
        *,
        request_intent: RequestIntentV1,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
        context_bundle: ContextBundleV1,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> tuple[SufficiencyOutputV1, dict[str, object]]:
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._sufficiency_prompt_ref,
            prompt_input={
                "request_intent": request_intent,
                "acquisition_status": acquisition_result["status"],
                "acquisition_missing_slots": list(acquisition_result["missing_slots"]),
                "context_bundle": context_bundle,
                "evidence_drafts": evidence_drafts,
                "source_content_is_untrusted": True,
            },
            output_schema=SUFFICIENCY_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:context.assess_sufficiency",
            ),
        )
        return validate_sufficiency_output_v1(llm_result.structured_output), _provider_summary(
            llm_result
        )


def validate_evidence_selection_output_v1(
    value: object,
    *,
    segments: list[_SourceSegment],
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> EvidenceSelectionOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "result",
            "selected_segment_ids",
            "evidence_drafts",
            "excluded_resource_handles",
            "missing_information",
            "ambiguity",
        },
    )
    _require_schema_version(root, "$")
    result = _require_string(root, "result", "$")
    if result not in _SELECTION_RESULT_VALUES:
        raise ContextRetrievalValidationError("$.result is invalid")
    selected_segment_ids = _require_string_list(
        root["selected_segment_ids"],
        "$.selected_segment_ids",
    )
    segment_ids = {segment.segment_id for segment in segments}
    for segment_id in selected_segment_ids:
        if segment_id not in segment_ids:
            raise ContextRetrievalValidationError(f"selected segment does not exist: {segment_id}")
    evidence = [
        _validate_evidence_draft(item, f"$.evidence_drafts[{index}]", context_budget)
        for index, item in enumerate(_require_list(root["evidence_drafts"], "$.evidence_drafts"))
    ]
    selected = set(selected_segment_ids)
    for draft in evidence:
        if draft["segment_id"] not in selected:
            raise ContextRetrievalValidationError(
                f"evidence references unselected segment: {draft['segment_id']}"
            )
    ambiguity = _nullable_mapping(root["ambiguity"], "$.ambiguity")
    return {
        "schema_version": 1,
        "result": cast(Literal["SELECTED", "PARTIAL", "BLOCKED"], result),
        "selected_segment_ids": selected_segment_ids,
        "evidence_drafts": evidence[: context_budget.max_evidence],
        "excluded_resource_handles": _require_string_list(
            root["excluded_resource_handles"],
            "$.excluded_resource_handles",
        ),
        "missing_information": _require_string_list(
            root["missing_information"],
            "$.missing_information",
        ),
        "ambiguity": ambiguity,
    }


def validate_sufficiency_output_v1(value: object) -> SufficiencyOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {"schema_version", "status", "sufficiency", "missing_slots", "ambiguity"},
    )
    _require_schema_version(root, "$")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise ContextRetrievalValidationError("$.status is invalid")
    return {
        "schema_version": 1,
        "status": cast(ContextStatusValue, status),
        "sufficiency": _require_mapping(root["sufficiency"], "$.sufficiency"),
        "missing_slots": _require_string_list(root["missing_slots"], "$.missing_slots"),
        "ambiguity": _nullable_mapping(root["ambiguity"], "$.ambiguity"),
    }


def validate_context_retrieval_result_v1(value: object) -> ContextRetrievalResultV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "status",
            "context_bundle",
            "evidence_drafts",
            "selected_segment_ids",
            "excluded_resource_handles",
            "missing_slots",
            "additional_acquisition_request",
            "sufficiency",
            "llm_provider_result",
        },
    )
    _require_schema_version(root, "$")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise ContextRetrievalValidationError("$.status is invalid")
    result = cast(ContextRetrievalResultV1, root)
    request = _nullable_mapping(
        root["additional_acquisition_request"],
        "$.additional_acquisition_request",
    )
    if request is not None:
        result["additional_acquisition_request"] = validate_additional_acquisition_request_v1(
            request,
            allowed_evidence_refs=set(result["context_bundle"]["evidence_refs"]),
        )
    _validate_context_result_invariant(result)
    return result


def build_context_clarification_question(
    *,
    result: ContextRetrievalResultV1,
    request_intent: RequestIntentV1,
) -> ClarificationQuestionV1:
    ambiguity = _require_mapping(
        result["context_bundle"]["ambiguity"], "$.context_bundle.ambiguity"
    )
    return build_clarification_question_v1(
        origin_target="context.assess_sufficiency",
        question=_require_string(ambiguity, "question", "$.context_bundle.ambiguity"),
        reason_code=_require_string(ambiguity, "reason_code", "$.context_bundle.ambiguity"),
        known_context_summary=request_intent["goal"]["user_visible_objective"]
        or request_intent["goal"]["summary"],
        affected_field_paths=_optional_string_list(ambiguity.get("affected_field_paths")),
        options=_optional_option_list(ambiguity.get("options")),
    )


def load_context_select_evidence_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "context.select_evidence",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_context_assess_sufficiency_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "context.assess_sufficiency",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def _segments_from_acquisition(
    acquisition_result: AcquisitionResultV1,
    context_budget: ContextBudget,
) -> list[_SourceSegment]:
    segments: list[_SourceSegment] = []
    seen: set[tuple[str, str]] = set()
    for source_summary in acquisition_result["source_summaries"]:
        source = str(source_summary.get("source", "UNKNOWN"))
        resources = source_summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for resource in resources:
            resource_map = _require_mapping(resource, "$.source_summaries[].resources[]")
            resource_handle = _require_string(resource_map, "resource_handle", "$.resource")
            text = _resource_text(resource_map)
            if not text.strip():
                continue
            dedupe_key = (resource_handle, text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            segment_id = f"seg-{len(segments) + 1}"
            segments.append(
                _SourceSegment(
                    segment_id=segment_id,
                    resource_handle=resource_handle,
                    source=source,
                    resource_type=str(resource_map.get("resource_type", "")),
                    resource_id=str(resource_map.get("resource_id", "")),
                    parent_id=_optional_string(resource_map.get("parent_id")),
                    version=_optional_string(resource_map.get("version")),
                    locator={"kind": "resource_payload", "position": len(segments)},
                    text=_truncate(text, context_budget.max_segment_chars),
                )
            )
            if len(segments) >= context_budget.max_segments:
                return segments
    return segments


def _resource_text(resource: dict[str, object]) -> str:
    payload = resource.get("payload")
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        for key, value in payload.items():
            if isinstance(value, str) and value.strip():
                parts.append(f"{key}: {value.strip()}")
    return "\n".join(parts)


def _selected_segments(
    selected_ids: list[str],
    *,
    segments: list[_SourceSegment],
) -> list[_SourceSegment]:
    by_id = {segment.segment_id: segment for segment in segments}
    return [by_id[segment_id] for segment_id in selected_ids]


def _validate_evidence_references(
    evidence_drafts: list[EvidenceDraftV1],
    *,
    selected_segments: list[_SourceSegment],
) -> None:
    selected_by_id = {segment.segment_id: segment for segment in selected_segments}
    for draft in evidence_drafts:
        segment = selected_by_id[draft["segment_id"]]
        if draft["resource_handle"] != segment.resource_handle:
            raise ContextRetrievalValidationError(
                f"evidence resource_handle mismatch: {draft['evidence_id']}"
            )


def _deduplicate_evidence(evidence: list[EvidenceDraftV1]) -> list[EvidenceDraftV1]:
    result: list[EvidenceDraftV1] = []
    seen: set[tuple[str, str, str]] = set()
    for draft in evidence:
        key = (draft["resource_handle"], draft["segment_id"], draft["excerpt"])
        if key in seen:
            continue
        seen.add(key)
        result.append(draft)
    return result


def _context_bundle(
    *,
    selected_segments: list[_SourceSegment],
    evidence_drafts: list[EvidenceDraftV1],
    missing_information: list[str],
    ambiguity: dict[str, object] | None,
    context_budget: ContextBudget,
) -> ContextBundleV1:
    return {
        "schema_version": 1,
        "resource_refs": [
            _resource_ref(segment) for segment in _unique_resources(selected_segments)
        ],
        "segment_refs": [_segment_ref(segment) for segment in selected_segments],
        "evidence_refs": [draft["evidence_id"] for draft in evidence_drafts],
        "normalized_context": [
            {
                "evidence_id": draft["evidence_id"],
                "resource_handle": draft["resource_handle"],
                "segment_id": draft["segment_id"],
                "kind": draft["kind"],
                "excerpt": draft["excerpt"],
            }
            for draft in evidence_drafts[: context_budget.max_normalized_context_items]
        ],
        "missing_information": list(missing_information),
        "ambiguity": ambiguity,
    }


def _build_additional_acquisition_request(
    *,
    status: ContextStatusValue,
    missing_slots: list[str],
    context_bundle: ContextBundleV1,
) -> AdditionalAcquisitionRequestV1 | None:
    if status != ContextResult.NEEDS_MORE_DATA.value:
        return None
    return {
        "schema_version": 1,
        "origin_phase": WorkflowPhase.CONTEXT_EVALUATION.value,
        "origin_result": AdditionalAcquisitionOriginResult.NEEDS_MORE_DATA.value,
        "missing_slots": list(missing_slots),
        "missing_information": list(context_bundle["missing_information"]),
        "evidence_refs": list(context_bundle["evidence_refs"]),
        "reason_codes": [],
    }


def _validate_context_result_invariant(result: ContextRetrievalResultV1) -> None:
    status = ContextResult(result["status"])
    request = result["additional_acquisition_request"]
    if status is ContextResult.NEEDS_MORE_DATA and request is None:
        raise ContextRetrievalValidationError(
            "NEEDS_MORE_DATA requires additional_acquisition_request"
        )
    if status is not ContextResult.NEEDS_MORE_DATA and request is not None:
        raise ContextRetrievalValidationError(
            "additional_acquisition_request is only allowed for NEEDS_MORE_DATA"
        )


def _unique_resources(segments: list[_SourceSegment]) -> list[_SourceSegment]:
    result: list[_SourceSegment] = []
    seen: set[str] = set()
    for segment in segments:
        if segment.resource_handle in seen:
            continue
        seen.add(segment.resource_handle)
        result.append(segment)
    return result


def _resource_ref(segment: _SourceSegment) -> dict[str, object]:
    return {
        "resource_handle": segment.resource_handle,
        "source": segment.source,
        "resource_type": segment.resource_type,
        "resource_id": segment.resource_id,
        "parent_id": segment.parent_id,
        "version": segment.version,
    }


def _segment_ref(segment: _SourceSegment) -> dict[str, object]:
    return {
        "segment_id": segment.segment_id,
        "resource_handle": segment.resource_handle,
        "source": segment.source,
        "locator": dict(segment.locator),
    }


def _segment_prompt_projection(segment: _SourceSegment) -> dict[str, object]:
    return {
        **_segment_ref(segment),
        "resource_type": segment.resource_type,
        "resource_id": segment.resource_id,
        "text": segment.text,
        "source_content_is_untrusted": True,
    }


def _budget_projection(budget: ContextBudget) -> dict[str, int]:
    return {
        "max_segments": budget.max_segments,
        "max_segment_chars": budget.max_segment_chars,
        "max_evidence": budget.max_evidence,
        "max_excerpt_chars": budget.max_excerpt_chars,
        "max_normalized_context_items": budget.max_normalized_context_items,
    }


def _validate_evidence_draft(
    value: object,
    path: str,
    context_budget: ContextBudget,
) -> EvidenceDraftV1:
    draft = _require_mapping(value, path)
    _require_exact_keys(
        draft,
        path,
        {
            "schema_version",
            "evidence_id",
            "resource_handle",
            "segment_id",
            "kind",
            "excerpt",
            "locator",
            "reason_codes",
        },
    )
    _require_schema_version(draft, path)
    return {
        "schema_version": 1,
        "evidence_id": _require_string(draft, "evidence_id", path),
        "resource_handle": _require_string(draft, "resource_handle", path),
        "segment_id": _require_string(draft, "segment_id", path),
        "kind": _require_string(draft, "kind", path),
        "excerpt": _truncate(
            _require_string(draft, "excerpt", path),
            context_budget.max_excerpt_chars,
        ),
        "locator": _nullable_mapping(draft["locator"], f"{path}.locator"),
        "reason_codes": _require_string_list(draft["reason_codes"], f"{path}.reason_codes"),
    }


def _provider_summary(result: StructuredLLMResult) -> dict[str, object]:
    return {
        "provider": result.provider,
        "model": result.model,
        "requested_mode": result.requested_mode.value,
        "actual_runtime": result.actual_runtime.value,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "latency_ms": result.latency_ms,
        "fallback_reason": result.fallback_reason,
        "structured_output_attempts": result.structured_output_attempts,
        "provider_request_id": result.provider_request_id,
        "safe_error_code": result.safe_error_code,
    }


def _require_schema_version(value: dict[str, object], path: str) -> None:
    schema_version = _require_int(value, "schema_version", path)
    if schema_version != CONTEXT_RETRIEVAL_SCHEMA_VERSION:
        raise ContextRetrievalValidationError(f"{path}.schema_version must be 1")


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContextRetrievalValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ContextRetrievalValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _nullable_mapping(value: object, path: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _require_mapping(value, path)


def _require_exact_keys(value: dict[str, object], path: str, keys: set[str]) -> None:
    actual = set(value)
    missing = keys - actual
    extra = actual - keys
    if missing:
        raise ContextRetrievalValidationError(
            f"{path} is missing required fields: {sorted(missing)}"
        )
    if extra:
        raise ContextRetrievalValidationError(f"{path} has unsupported fields: {sorted(extra)}")


def _require_int(value: dict[str, object], field: str, path: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise ContextRetrievalValidationError(f"{path}.{field} must be integer")
    return item


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise ContextRetrievalValidationError(f"{path}.{field} must be string")
    return item


def _require_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ContextRetrievalValidationError(f"{path} must be an array")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    items = _require_list(value, path)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise ContextRetrievalValidationError(f"{path}[{index}] must be string")
    return cast(list[str], items)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.list")
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise ContextRetrievalValidationError(
                f"clarification list entry must be string: {index}"
            )
        result.append(item)
    return result


def _optional_option_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.options")
    return [_require_mapping(item, "$.clarification.options[]") for item in items]


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars]
