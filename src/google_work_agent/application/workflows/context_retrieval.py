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
    BudgetDecision,
    ContextResult,
    GraphStateUpdateV1,
    RunBudgetV1,
    WorkflowPhase,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
    validate_additional_acquisition_request_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    ClarificationQuestionV1,
    ContextBundleV1,
    ContextRetrievalResultV1,
    ContextStatusValue,
    EvidenceDraftV1,
    EvidenceRoleDraftV2,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    SufficiencyResultV2,
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
from google_work_agent.application.workflows.retrieval_ranking import (
    RagCandidateV1 as RagCandidateV1,
)
from google_work_agent.application.workflows.retrieval_ranking import (
    rank_segments as rank_segments,
)
from google_work_agent.application.workflows.retrieval_sufficiency import (
    SUFFICIENCY_OUTPUT_SCHEMA,
    budget_state_prompt_projection,
    default_run_budget,
    enforce_sufficiency_guard,
    missing_information_projection,
    selected_evidence_prompt_projection,
    source_statuses_prompt_projection,
    sufficiency_ambiguity_projection,
    validate_sufficiency_result_v2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
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
_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}
_EVIDENCE_ROLE_VALUES = {"SUPPORTS", "CONTRADICTS", "CONTEXT"}


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

    def rag_retrieve(
        self,
        segments: list[_SourceSegment],
        *,
        request_intent: RequestIntentV2,
    ) -> list[RagCandidateV1]:
        """retrieval.rag_retrieve (docs/05-context-retrieval.md SS5.5): rank
        already-normalized Segments and bound them to the Context Budget.
        Retrieval Local State only -- see rank_segments docstring."""
        return rank_segments(
            segments,
            request_intent=request_intent,
            top_k=self._context_budget.max_segments,
        )

    def retrieve(
        self,
        *,
        request_intent: RequestIntentV2,
        acquisition_result: AcquisitionResultV1,
        request: WorkflowStartRequest,
        tool_route_plan: ToolRoutePlanV2 | None = None,
        retry_budget: RunBudgetV1 | None = None,
    ) -> ContextRetrievalResultV1:
        segments = cast(
            list[_SourceSegment],
            self.build_segments_from_acquisition(acquisition_result),
        )
        rag_candidates = self.rag_retrieve(segments, request_intent=request_intent)
        selection_result, revised_retry_budget = self.select_evidence(
            request_intent=request_intent,
            request=request,
            rag_candidates=rag_candidates,
            segments=segments,
            retry_budget=retry_budget or default_run_budget(),
        )
        _draft_bundle, evidence_drafts = self.build_draft_context_bundle(
            selection_result=selection_result,
            acquisition_result=acquisition_result,
        )
        sufficiency_result, llm_provider_result = self.assess_sufficiency(
            request_intent=request_intent,
            request=request,
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
            retry_budget=revised_retry_budget,
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
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        rag_candidates: list[RagCandidateV1],
        segments: list[_SourceSegment],
        retry_budget: RunBudgetV1,
    ) -> tuple[EvidenceSelectionResultV2, RunBudgetV1]:
        segments_by_id = {segment.segment_id: segment for segment in segments}
        ranked_segments = _ranked_segments_prompt_projection(
            rag_candidates, segments_by_id=segments_by_id
        )
        candidate_segment_ids = {candidate["segment_id"] for candidate in rag_candidates}
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "ranked_segments": ranked_segments,
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
            return (
                validate_evidence_selection_result_v2(
                    llm_result.structured_output,
                    candidate_segment_ids=candidate_segment_ids,
                ),
                retry_budget,
            )
        except ContextRetrievalValidationError as error:
            return self._revise_selection_once(
                request_intent=request_intent,
                request=request,
                rag_candidates=rag_candidates,
                segments_by_id=segments_by_id,
                previous_output=llm_result.structured_output,
                failure_detail=str(error),
                retry_budget=retry_budget,
            )

    def _revise_selection_once(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        rag_candidates: list[RagCandidateV1],
        segments_by_id: dict[str, _SourceSegment],
        previous_output: object,
        failure_detail: str,
        retry_budget: RunBudgetV1,
    ) -> tuple[EvidenceSelectionResultV2, RunBudgetV1]:
        """Bounded SEMANTIC_REVISION retry (docs/15 section 8.1: max 1 per Node per
        Failure Signature). The initial validator already rejected the output as
        SEMANTIC_INVALID; this never widens what counts as valid, it only gives the
        model one chance to re-ground its selection in the actually-supplied
        ranked_segments. If the revision also fails validation, a deterministic empty
        selection is returned -- the LLM never gets a second judgment call.

        G3: same-Run/same-node dedup via approve_semantic_revision -- once this
        node has already spent its one revision attempt for the normalized
        failure signature below (persisted in
        retry_budget.semantic_revision_signatures_used, so it survives
        resume/checkpoint restore), a second occurrence is denied before any
        Provider call and falls back to the same deterministic empty
        selection a failed revision would produce."""
        signature = build_semantic_failure_signature_v1(
            node_id="context.select_evidence",
            failure_reason_codes=["EVIDENCE_SELECTION_SEMANTIC_INVALID"],
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            return _blocked_empty_selection(), decision["run_budget"]
        ranked_segments = _ranked_segments_prompt_projection(
            rag_candidates, segments_by_id=segments_by_id
        )
        candidate_segment_ids = {candidate["segment_id"] for candidate in rag_candidates}
        revision_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_revision_prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "ranked_segments": ranked_segments,
                "previous_output": previous_output,
                "failure_reason": failure_detail,
                "changed_fields_allowed": [
                    "$.selected_segment_ids",
                    "$.evidence_drafts",
                    "$.excluded_segment_ids",
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
            return (
                validate_evidence_selection_result_v2(
                    revision_result.structured_output,
                    candidate_segment_ids=candidate_segment_ids,
                ),
                decision["run_budget"],
            )
        except ContextRetrievalValidationError:
            return _blocked_empty_selection(), decision["run_budget"]

    def assess_sufficiency(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        tool_route_plan: ToolRoutePlanV2 | None,
        acquisition_result: AcquisitionResultV1,
        evidence_drafts: list[EvidenceDraftV1],
        retry_budget: RunBudgetV1,
    ) -> tuple[SufficiencyResultV2, dict[str, object]]:
        """retrieval.assess_sufficiency (docs/05-context-retrieval.md SS5.7):
        request_intent + top rag candidates' materialized evidence. Never
        re-sends the full context_bundle/acquisition_status opaque blob --
        only the Candidate-pinned selected_evidence/source_statuses/
        budget_state typed projections."""
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._sufficiency_prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "selected_evidence": selected_evidence_prompt_projection(evidence_drafts),
                "source_statuses": source_statuses_prompt_projection(
                    tool_route_plan=tool_route_plan,
                    acquisition_result=acquisition_result,
                ),
                "budget_state": budget_state_prompt_projection(retry_budget),
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
            semantic_validate=validate_sufficiency_result_v2,
        )
        validated = validate_sufficiency_result_v2(llm_result.structured_output)
        enforced = enforce_sufficiency_guard(
            validated,
            request_intent=request_intent,
            retry_budget=retry_budget,
            evidence_supported_partial_possible=bool(evidence_drafts),
        )
        return enforced, _provider_summary(llm_result)

    def build_result_from_outputs(
        self,
        *,
        selection_result: EvidenceSelectionResultV2,
        sufficiency_result: SufficiencyResultV2,
        acquisition_result: AcquisitionResultV1,
        llm_provider_result: dict[str, object],
    ) -> ContextRetrievalResultV1:
        segments = cast(
            list[_SourceSegment],
            self.build_segments_from_acquisition(acquisition_result),
        )
        selected_segments = _selected_segments(
            selection_result["selected_segment_ids"],
            segments=segments,
        )
        evidence_drafts = _materialize_evidence_drafts(
            selection_result["evidence_drafts"],
            segments=segments,
            context_budget=self._context_budget,
        )
        missing_information = missing_information_projection(sufficiency_result["issues"])
        missing_slots = [item["code"] for item in missing_information]
        context_bundle = _context_bundle(
            selected_segments=selected_segments,
            evidence_drafts=evidence_drafts,
            missing_information=missing_slots,
            ambiguity=sufficiency_ambiguity_projection(sufficiency_result),
            context_budget=self._context_budget,
        )
        return {
            "schema_version": 1,
            "status": sufficiency_result["status"],
            "context_bundle": context_bundle,
            "evidence_drafts": evidence_drafts,
            "selected_segment_ids": list(selection_result["selected_segment_ids"]),
            "excluded_resource_handles": _resource_handles_for_segment_ids(
                selection_result["excluded_segment_ids"],
                segments=segments,
            ),
            "missing_slots": missing_slots,
            "additional_acquisition_request": _build_additional_acquisition_request(
                status=sufficiency_result["status"],
                missing_slots=missing_slots,
                context_bundle=context_bundle,
                evidence_drafts=evidence_drafts,
            ),
            "sufficiency": {
                "status": sufficiency_result["status"],
                "issues": list(sufficiency_result["issues"]),
            },
            "llm_provider_result": llm_provider_result,
        }

    def build_selected_segments(
        self,
        *,
        selection_result: EvidenceSelectionResultV2,
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
        selection_result: EvidenceSelectionResultV2,
        acquisition_result: AcquisitionResultV1,
    ) -> tuple[ContextBundleV1, list[EvidenceDraftV1]]:
        """Pre-sufficiency draft: assess_sufficiency has not run yet at this
        point in the pipeline, so missing_information/ambiguity are not yet
        known -- that judgment is entirely assess_sufficiency's (docs/05
        section 5.7), not select_evidence's."""
        segments = cast(
            list[_SourceSegment],
            self.build_segments_from_acquisition(acquisition_result),
        )
        selected_segments = _selected_segments(
            selection_result["selected_segment_ids"],
            segments=segments,
        )
        evidence_drafts = _materialize_evidence_drafts(
            selection_result["evidence_drafts"],
            segments=segments,
            context_budget=self._context_budget,
        )
        return (
            _context_bundle(
                selected_segments=selected_segments,
                evidence_drafts=evidence_drafts,
                missing_information=[],
                ambiguity=None,
                context_budget=self._context_budget,
            ),
            evidence_drafts,
        )


def _blocked_empty_selection() -> EvidenceSelectionResultV2:
    """Deterministic fallback once the bounded SEMANTIC_REVISION retry is exhausted.

    Trivially schema- and semantically-valid (empty lists are always a valid
    subset of the supplied ranked_segments), so it never re-enters LLM
    judgment -- downstream sufficiency/supervisor routing treats it as
    insufficient context and proceeds through the normal
    RETRIEVE_MORE/BLOCKED guard instead of the node crashing.
    """

    return {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
    }


def validate_evidence_selection_result_v2(
    value: object,
    *,
    candidate_segment_ids: set[str],
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> EvidenceSelectionResultV2:
    """evidence-selection-result-v2.schema.json. ``candidate_segment_ids`` is
    the bounded RAG top-K set actually sent as ``ranked_segments`` (docs/05
    section 5.6/5.5) -- selected/excluded ids outside it, or evidence
    referencing an unselected segment, are rejected rather than silently
    accepted, so select_evidence can never introduce a Segment/Resource RAG
    never surfaced."""
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "evidence_drafts",
            "selected_segment_ids",
            "excluded_segment_ids",
        },
    )
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != 2:
        raise ContextRetrievalValidationError("$.schema_version must be 2")
    selected_segment_ids = _require_string_list(
        root["selected_segment_ids"],
        "$.selected_segment_ids",
    )
    excluded_segment_ids = _require_string_list(
        root["excluded_segment_ids"],
        "$.excluded_segment_ids",
    )
    if len(set(selected_segment_ids)) != len(selected_segment_ids):
        raise ContextRetrievalValidationError("$.selected_segment_ids has duplicates")
    if len(set(excluded_segment_ids)) != len(excluded_segment_ids):
        raise ContextRetrievalValidationError("$.excluded_segment_ids has duplicates")
    for segment_id in (*selected_segment_ids, *excluded_segment_ids):
        if segment_id not in candidate_segment_ids:
            raise ContextRetrievalValidationError(
                f"segment is outside ranked candidates: {segment_id}"
            )
    overlap = set(selected_segment_ids) & set(excluded_segment_ids)
    if overlap:
        raise ContextRetrievalValidationError(
            f"segment is both selected and excluded: {sorted(overlap)}"
        )
    selected = set(selected_segment_ids)
    evidence = [
        _validate_evidence_role_draft(item, f"$.evidence_drafts[{index}]", selected)
        for index, item in enumerate(_require_list(root["evidence_drafts"], "$.evidence_drafts"))
    ]
    return {
        "schema_version": 2,
        "evidence_drafts": evidence[: context_budget.max_evidence],
        "selected_segment_ids": selected_segment_ids,
        "excluded_segment_ids": excluded_segment_ids,
    }


def _validate_evidence_role_draft(
    value: object,
    path: str,
    selected_segment_ids: set[str],
) -> EvidenceRoleDraftV2:
    draft = _require_mapping(value, path)
    _require_exact_keys(draft, path, {"segment_id", "role", "relevance_reason"})
    segment_id = _require_string(draft, "segment_id", path)
    if segment_id not in selected_segment_ids:
        raise ContextRetrievalValidationError(
            f"evidence references unselected segment: {segment_id}"
        )
    role = _require_string(draft, "role", path)
    if role not in _EVIDENCE_ROLE_VALUES:
        raise ContextRetrievalValidationError(f"{path}.role is invalid")
    return {
        "segment_id": segment_id,
        "role": cast(Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"], role),
        "relevance_reason": _require_string(draft, "relevance_reason", path),
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
    request_intent: RequestIntentV2,
) -> ClarificationQuestionV1:
    ambiguity = _require_mapping(
        result["context_bundle"]["ambiguity"], "$.context_bundle.ambiguity"
    )
    return build_clarification_question_v1(
        origin_target="context.assess_sufficiency",
        question=_require_string(ambiguity, "question", "$.context_bundle.ambiguity"),
        reason_code=_require_string(ambiguity, "reason_code", "$.context_bundle.ambiguity"),
        known_context_summary=request_intent["goal"],
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


def _ranked_segments_prompt_projection(
    rag_candidates: list[RagCandidateV1],
    *,
    segments_by_id: dict[str, _SourceSegment],
) -> list[dict[str, object]]:
    """retrieval-evidence-selection-input-v1.schema.json ``ranked_segments``.

    Joins each RagCandidateV1 back to its normalized SourceSegment by
    segment_id -- docs/05 section 5.6/Q2-RAG boundary: RagCandidateV1 never
    carries body text itself, and this never re-scores or re-orders what
    Q2-RAG already ranked."""
    projections: list[dict[str, object]] = []
    for candidate in rag_candidates:
        segment = segments_by_id.get(candidate["segment_id"])
        if segment is None:
            raise ContextRetrievalValidationError(
                f"RAG_SEGMENT_REFERENCE_INVALID: {candidate['segment_id']}"
            )
        projections.append(
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
    return projections


def _materialize_evidence_drafts(
    role_drafts: list[EvidenceRoleDraftV2],
    *,
    segments: list[_SourceSegment],
    context_budget: ContextBudget,
) -> list[EvidenceDraftV1]:
    """Join the LLM's thin role/segment reference back to its normalized
    SourceSegment -- docs/05-context-retrieval.md section 5.6 forbids the
    LLM from copying Connector body text into its own output, so
    resource_handle/excerpt/locator always come from the Segment, never
    from the LLM."""
    segments_by_id = {segment.segment_id: segment for segment in segments}
    drafts: list[EvidenceDraftV1] = []
    for role_draft in role_drafts:
        segment = segments_by_id.get(role_draft["segment_id"])
        if segment is None:
            raise ContextRetrievalValidationError(
                f"RAG_SEGMENT_REFERENCE_INVALID: {role_draft['segment_id']}"
            )
        drafts.append(
            {
                "schema_version": 1,
                "evidence_id": f"evidence-{role_draft['segment_id']}",
                "resource_handle": segment.resource_handle,
                "segment_id": role_draft["segment_id"],
                "kind": "excerpt",
                "excerpt": _truncate(segment.text, context_budget.max_excerpt_chars),
                "locator": dict(segment.locator),
                "reason_codes": [role_draft["role"]],
            }
        )
    return _deduplicate_evidence(drafts)


def _resource_handles_for_segment_ids(
    segment_ids: list[str],
    *,
    segments: list[_SourceSegment],
) -> list[str]:
    by_id = {segment.segment_id: segment for segment in segments}
    handles: list[str] = []
    seen: set[str] = set()
    for segment_id in segment_ids:
        segment = by_id.get(segment_id)
        if segment is None:
            raise ContextRetrievalValidationError(
                f"RAG_SEGMENT_REFERENCE_INVALID: {segment_id}"
            )
        if segment.resource_handle in seen:
            continue
        seen.add(segment.resource_handle)
        handles.append(segment.resource_handle)
    return handles


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
