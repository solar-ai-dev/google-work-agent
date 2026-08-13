"""Context retrieval workflow node implementation."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Literal, cast

import google_work_agent.application.workflows._schema_support as _schema
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.context_segmentation import (
    DEFAULT_CONTEXT_BUDGET,
    _SourceSegment,
    _truncate,
)
from google_work_agent.application.workflows.context_segmentation import (
    ContextBudget as ContextBudget,
)
from google_work_agent.application.workflows.context_segmentation import (
    ContextRetrievalValidationError as ContextRetrievalValidationError,
)
from google_work_agent.application.workflows.context_segmentation import (
    _chunk_text as _chunk_text,
)
from google_work_agent.application.workflows.context_segmentation import (
    _estimate_tokens as _estimate_tokens,
)
from google_work_agent.application.workflows.context_segmentation import (
    _segments_from_acquisition as _segments_from_acquisition,
)
from google_work_agent.application.workflows.context_segmentation import (
    _strip_email_quote_and_signature as _strip_email_quote_and_signature,
)
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    ContextResult,
    GraphStateUpdateV1,
    WorkflowPhase,
    validate_additional_acquisition_request_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    ClarificationQuestionV1,
    ContextBundleV1,
    ContextRetrievalResultV1,
    ContextStatusValue,
    EvidenceDraftV1,
    EvidenceSelectionOutputV1,
    RequestIntentV1,
    SufficiencyOutputV1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.workflows.request_understanding import (
    build_clarification_question_v1,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]





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
            "evidence_drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "schema_version",
                        "evidence_id",
                        "resource_handle",
                        "segment_id",
                        "kind",
                        "excerpt",
                        "locator",
                        "reason_codes",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "schema_version": {"type": "integer", "enum": [1]},
                        "evidence_id": {"type": "string", "minLength": 1},
                        "resource_handle": {"type": "string", "minLength": 1},
                        "segment_id": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "minLength": 1},
                        "excerpt": {"type": "string", "minLength": 1},
                        "locator": {"type": ["object", "null"]},
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "excluded_resource_handles": {"type": "array", "items": {"type": "string"}},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "ambiguity": {"type": ["object", "null"]},
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
            "ambiguity": {"type": ["object", "null"]},
        },
    },
)

_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}
_SELECTION_RESULT_VALUES = {"SELECTED", "PARTIAL", "BLOCKED"}


class ContextRetrievalAgent:
    """Build a minimal context bundle from Stage 5 acquisition output."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        select_prompt_ref: PromptReference | None = None,
        sufficiency_prompt_ref: PromptReference | None = None,
        select_revision_prompt_ref: PromptReference | None = None,
        context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._select_prompt_ref = (
            select_prompt_ref or load_context_select_evidence_prompt_reference(manifest_path)
        )
        self._sufficiency_prompt_ref = (
            sufficiency_prompt_ref
            or load_context_assess_sufficiency_prompt_reference(manifest_path)
        )
        self._select_revision_prompt_ref = (
            select_revision_prompt_ref
            or load_context_select_evidence_semantic_revision_prompt_reference(manifest_path)
        )
        self._context_budget = context_budget

    @property
    def select_prompt_ref(self) -> PromptReference:
        return self._select_prompt_ref

    @property
    def sufficiency_prompt_ref(self) -> PromptReference:
        return self._sufficiency_prompt_ref

    def build_segments_from_acquisition(
        self,
        acquisition_result: AcquisitionResultV1,
    ) -> list[object]:
        return cast(
            list[object],
            _segments_from_acquisition(acquisition_result, self._context_budget),
        )

    def retrieve(
        self,
        *,
        request_intent: RequestIntentV1,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
    ) -> ContextRetrievalResultV1:
        segments = cast(
            list[_SourceSegment],
            self.build_segments_from_acquisition(acquisition_result),
        )
        selection_result = self.select_evidence(
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
        sufficiency_result, llm_provider_result = self.assess_sufficiency(
            request_intent=request_intent,
            acquisition_result=acquisition_result,
            request=request,
            context_bundle=draft_bundle,
            evidence_drafts=evidence_drafts,
        )
        return self.build_result_from_outputs(
            selection_result=selection_result,
            sufficiency_result=sufficiency_result,
            acquisition_result=acquisition_result,
            llm_provider_result=llm_provider_result,
        )

    def build_state_update(self, result: ContextRetrievalResultV1) -> GraphStateUpdateV1:
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

    def select_evidence(
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
        try:
            return validate_evidence_selection_output_v1(
                llm_result.structured_output,
                segments=segments,
                context_budget=self._context_budget,
            )
        except ContextRetrievalValidationError as error:
            return self._revise_selection_once(
                request_intent=request_intent,
                acquisition_result=acquisition_result,
                request=request,
                segments=segments,
                previous_output=llm_result.structured_output,
                failure_detail=str(error),
            )

    def _revise_selection_once(
        self,
        *,
        request_intent: RequestIntentV1,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
        segments: list[_SourceSegment],
        previous_output: object,
        failure_detail: str,
    ) -> EvidenceSelectionOutputV1:
        """Bounded SEMANTIC_REVISION retry (docs/15 section 8.1: max 1 per Node per
        Failure Signature). The initial validator already rejected the output as
        SEMANTIC_INVALID; this never widens what counts as valid, it only gives the
        model one chance to re-ground its selection in the actually-supplied
        segments. If the revision also fails validation, a deterministic empty
        selection is returned -- the LLM never gets a second judgment call."""
        revision_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_revision_prompt_ref,
            prompt_input={
                "request_intent": request_intent,
                "acquisition_status": acquisition_result["status"],
                "acquisition_missing_slots": list(acquisition_result["missing_slots"]),
                "source_content_is_untrusted": True,
                "segments": [_segment_prompt_projection(segment) for segment in segments],
                "context_budget": _budget_projection(self._context_budget),
                "previous_output": previous_output,
                "failure_reason": failure_detail,
                "changed_fields_allowed": [
                    "$.selected_segment_ids",
                    "$.evidence_drafts",
                    "$.excluded_resource_handles",
                ],
            },
            output_schema=EVIDENCE_SELECTION_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:context.select_evidence.semantic_revision",
            ),
        )
        try:
            return validate_evidence_selection_output_v1(
                revision_result.structured_output,
                segments=segments,
                context_budget=self._context_budget,
            )
        except ContextRetrievalValidationError:
            return _blocked_empty_selection()

    def assess_sufficiency(
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
            semantic_validate=validate_sufficiency_output_v1,
        )
        return validate_sufficiency_output_v1(llm_result.structured_output), _provider_summary(
            llm_result
        )

    def build_result_from_outputs(
        self,
        *,
        selection_result: EvidenceSelectionOutputV1,
        sufficiency_result: SufficiencyOutputV1,
        acquisition_result: AcquisitionResultV1,
        llm_provider_result: dict[str, object],
    ) -> ContextRetrievalResultV1:
        context_bundle, evidence_drafts = self.build_draft_context_bundle(
            selection_result=selection_result,
            acquisition_result=acquisition_result,
            missing_information=selection_result["missing_information"],
            ambiguity=selection_result["ambiguity"],
        )
        context_bundle = _context_bundle(
            selected_segments=cast(
                list[_SourceSegment],
                self.build_selected_segments(
                    selection_result=selection_result,
                    acquisition_result=acquisition_result,
                ),
            ),
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
                evidence_drafts=evidence_drafts,
            ),
            "sufficiency": dict(sufficiency_result["sufficiency"]),
            "llm_provider_result": llm_provider_result,
        }

    def build_selected_segments(
        self,
        *,
        selection_result: EvidenceSelectionOutputV1,
        acquisition_result: AcquisitionResultV1,
    ) -> list[object]:
        segments = cast(
            list[_SourceSegment],
            self.build_segments_from_acquisition(acquisition_result),
        )
        return cast(
            list[object],
            _selected_segments(
                selection_result["selected_segment_ids"],
                segments=segments,
            ),
        )

    def build_draft_context_bundle(
        self,
        *,
        selection_result: EvidenceSelectionOutputV1,
        acquisition_result: AcquisitionResultV1,
        missing_information: list[str],
        ambiguity: dict[str, object] | None,
    ) -> tuple[ContextBundleV1, list[EvidenceDraftV1]]:
        selected_segments = cast(
            list[_SourceSegment],
            self.build_selected_segments(
                selection_result=selection_result,
                acquisition_result=acquisition_result,
            ),
        )
        evidence_drafts = _deduplicate_evidence(selection_result["evidence_drafts"])
        _validate_evidence_references(evidence_drafts, selected_segments=selected_segments)
        return (
            _context_bundle(
                selected_segments=selected_segments,
                evidence_drafts=evidence_drafts,
                missing_information=missing_information,
                ambiguity=ambiguity,
                context_budget=self._context_budget,
            ),
            evidence_drafts,
        )


def _blocked_empty_selection() -> EvidenceSelectionOutputV1:
    """Deterministic fallback once the bounded SEMANTIC_REVISION retry is exhausted.

    Trivially schema- and semantically-valid (empty lists are always a valid
    subset of the supplied segments), so it never re-enters LLM judgment --
    downstream sufficiency/supervisor routing treats it as insufficient context
    and proceeds through the normal RETRIEVE_MORE/BLOCKED guard instead of the
    node crashing.
    """

    return {
        "schema_version": 1,
        "result": "BLOCKED",
        "selected_segment_ids": [],
        "evidence_drafts": [],
        "excluded_resource_handles": [],
        "missing_information": ["context_selection_semantic_revision_failed"],
        "ambiguity": None,
    }


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
        "retrieval.select_evidence",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_context_assess_sufficiency_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "retrieval.assess_sufficiency",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_context_select_evidence_semantic_revision_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "retrieval.select_evidence.revise",
        manifest_path or _registry_default_prompt_manifest_path(),
    )





# Common quoted-reply and signature markers across Gmail clients (English and
# Korean). Best-effort/heuristic by nature -- docs/05 section 6 requires
# "Gmail HTML 안전 텍스트 변환, 인용·서명 제거" as a Context Retriever
# responsibility, but does not pin an exhaustive pattern list.


# Retrieval Chunk Token is a Provider-independent deterministic estimated
# token unit, not a claim of exact parity with any real Provider's
# tokenizer/billing count (see docs/05-context-retrieval.md section 10).
# It is measured as UTF-8 byte length: for byte-level BPE tokenizers (the
# family essentially every current LLM provider uses, including this
# project's active Ollama/Qwen and Gemini providers), a single token is
# always built from one or more whole input bytes -- a tokenizer merges
# bytes together, it never splits one byte into multiple tokens. That
# makes "1 estimated unit per UTF-8 byte" a theoretically sound upper
# bound on real token count for any such tokenizer, not merely a guess:
# real_tokens <= utf8_byte_length always holds.
#
# This was calibrated against a locally running Ollama qwen2.5:3b
# (/api/generate with raw=true, reading prompt_eval_count) across English,
# Korean, Korean/English-mixed, URL/email/number, and Gmail-reply-shaped
# samples. Natural-language text (English, Korean, mixed) measured well
# under 1 real token per byte, but digit/punctuation-dense text (order
# numbers, IDs, timestamps -- realistic in Gmail bodies) measured as high
# as 1.0 real tokens per byte (pure digit sequences: qwen2.5 tokenizes
# purely digit-by-digit). No sample exceeded 1 real token per byte, which
# matches the byte-level-BPE argument above. Earlier chars/4 undercounted
# Korean by up to ~2.5x and digit-heavy text by up to ~3.4x against this
# same real measurement -- both silently violated the "no chunk exceeds
# chunk_max_tokens" contract for an actual provider call.
#
# Trade-off: this is intentionally conservative, so ordinary English/Korean
# prose chunks end up smaller in characters than the old chars/4 estimate
# allowed (chunks are sized for the digit-dense worst case even when actual
# content is natural language). That is the accepted cost of an honest
# never-exceeds guarantee without adding a tokenizer dependency; it is not
# a per-script/per-language heuristic -- the same byte-count formula runs
# unconditionally for every Unicode input.



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
    evidence_drafts: list[EvidenceDraftV1],
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
        "reason_codes": _merged_evidence_reason_codes(evidence_drafts),
    }


def _merged_evidence_reason_codes(evidence_drafts: list[EvidenceDraftV1]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for draft in evidence_drafts:
        for code in draft["reason_codes"]:
            if code in seen:
                continue
            seen.add(code)
            merged.append(code)
    return merged


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


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=ContextRetrievalValidationError)
_nullable_mapping = partial(_schema.nullable_mapping, error_cls=ContextRetrievalValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=ContextRetrievalValidationError)
_require_int = partial(_schema.require_int, error_cls=ContextRetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=ContextRetrievalValidationError)
_require_list = partial(_schema.require_list, error_cls=ContextRetrievalValidationError)
_require_string_list = partial(
    _schema.require_string_list, error_cls=ContextRetrievalValidationError
)
_require_schema_version = partial(
    _schema.require_schema_version,
    expected=CONTEXT_RETRIEVAL_SCHEMA_VERSION,
    error_cls=ContextRetrievalValidationError,
)
_optional_string_list = partial(
    _schema.optional_string_list, error_cls=ContextRetrievalValidationError
)
_optional_option_list = partial(
    _schema.optional_option_list, error_cls=ContextRetrievalValidationError
)
_provider_summary = _schema.provider_summary
