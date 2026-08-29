"""Work analysis workflow node implementation."""

from __future__ import annotations

from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Literal, TypedDict, cast

import google_work_agent.application.orchestration._schema_support as _schema
from google_work_agent.application.orchestration.confirmation import (
    build_clarification_question_v1,
)
from google_work_agent.application.orchestration.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    AnalysisResult,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    WorkflowPhase,
    validate_additional_acquisition_request_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AnalysisFindingKind,
    AnalysisFindingV1,
    AnalysisStatusValue,
    ClarificationQuestionV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    FeasibilityScheduleConstraintsV1,
    RequestIntentV2,
    RetrievalResultV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.planning_argument_writer import (
    _planning_evidence_projection,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

JsonObject = dict[str, object]
WORK_ANALYSIS_SCHEMA_VERSION = 1
ANALYSIS_FINDING_SCHEMA_VERSION = 1
WORK_ANALYSIS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-analysis-v1",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "summary",
            "findings",
            "missing_information",
            "confirmation",
            "blockers",
            "evidence_refs",
            "resource_refs",
            "segment_refs",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "status": {
                "type": "string",
                "enum": [
                    "COMPLETE",
                    "NEEDS_MORE_DATA",
                    "NEEDS_CONFIRMATION",
                    "ROUTE_RECONSIDERATION_REQUIRED",
                    "BLOCKED",
                ],
            },
            "summary": {"type": "string"},
            # Nested finding shape mirrors AnalysisFindingV1 exactly (required
            # field names + kind enum) rather than a bare {"type": "object"}:
            # without this, Ollama's structured-output constraint gave the
            # model zero guidance on the finding's internal field names,
            # confirmed empirically to produce foreign shapes like
            # {"finding": ..., "source": ..., "confidence": ...} instead of
            # finding_id/kind/statement/evidence_refs/... (Node Contract
            # Stability Runner, qwen2.5:7b). UNSUPPORTED_INFERENCE is
            # deliberately excluded from the enum -- _PROHIBITED_FINDING_KINDS
            # below already rejects it; omitting it from the constrained
            # decoder's own choices is strictly safer, not narrower semantics.
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "schema_version",
                        "finding_id",
                        "kind",
                        "statement",
                        "evidence_refs",
                        "resource_refs",
                        "segment_refs",
                        "related_resource_handles",
                        "reason_codes",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "schema_version": {"type": "integer", "enum": [1]},
                        "finding_id": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": [
                                "FACT",
                                "RELATIONSHIP",
                                "MISSING_INFORMATION",
                                "DUPLICATE_CANDIDATE",
                                "CONFLICT",
                                "SCHEDULE_RISK",
                                "EVIDENCE_GAP",
                            ],
                        },
                        "statement": {"type": "string"},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        "resource_refs": {"type": "array", "items": {"type": "string"}},
                        "segment_refs": {"type": "array", "items": {"type": "string"}},
                        "related_resource_handles": {"type": "array", "items": {"type": "string"}},
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "confirmation": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            # resource_refs/segment_refs items are context_bundle entries the
            # model echoes back (see _validated_resource_ref_objects/
            # _validated_segment_ref_objects below, which only require
            # resource_handle/segment_id and tolerate extra fields) --
            # additionalProperties stays permissive here, unlike findings[]
            # above, which is a closed, model-authored contract.
            "resource_refs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["resource_handle"],
                    "properties": {"resource_handle": {"type": "string"}},
                },
            },
            "segment_refs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["segment_id"],
                    "properties": {"segment_id": {"type": "string"}},
                },
            },
            "schedule_constraints": {
                "type": "object",
                "required": [
                    "business_deadline",
                    "business_deadline_source",
                    "expected_duration_minutes",
                    "duration_source",
                ],
                "additionalProperties": False,
                "properties": {
                    "business_deadline": {"type": "string", "minLength": 1},
                    "business_deadline_source": {
                        "type": "string",
                        "enum": ["USER", "GMAIL_EVIDENCE"],
                    },
                    "expected_duration_minutes": {"type": ["integer", "null"]},
                    "duration_source": {
                        "type": "string",
                        "enum": ["EXPLICIT_ESTIMATE", "EVENT_INTERVAL"],
                    },
                },
            },
        },
    },
)

_ANALYSIS_RESULT_VALUES = {item.value for item in AnalysisResult}
_FINDING_KIND_VALUES = {
    "FACT",
    "RELATIONSHIP",
    "MISSING_INFORMATION",
    "DUPLICATE_CANDIDATE",
    "CONFLICT",
    "SCHEDULE_RISK",
    "EVIDENCE_GAP",
}
_PROHIBITED_FINDING_KINDS = {"UNSUPPORTED_INFERENCE"}
_PROHIBITED_REASON_CODES = {"ANALYSIS_UNSUPPORTED_INFERENCE"}


class WorkAnalysisValidationError(ValueError):
    """Raised when work analysis structured output is invalid."""


class WorkAnalysisAgent:
    """Analyze Stage 6 context without planning, execution, or external calls."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        analyze_prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._analyze_prompt_ref = (
            analyze_prompt_ref or load_work_analysis_analyze_prompt_reference(manifest_path)
        )

    @property
    def analyze_prompt_ref(self) -> PromptReference:
        return self._analyze_prompt_ref

    def analyze(
        self,
        *,
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        request: WorkflowStartRequest,
    ) -> WorkAnalysisResultV1:
        llm_result = self.invoke_analyze_llm(
            request_intent=request_intent,
            context_result=context_result,
            request=request,
        )
        return self.build_output_from_llm_result(llm_result, context_result=context_result)

    def invoke_analyze_llm(
        self,
        *,
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        request: WorkflowStartRequest,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._analyze_prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "evidence": _planning_evidence_projection(context_result["evidence_drafts"]),
                "availability_results": [],
                "policy_confirmation_receipt_refs": [],
            },
            output_schema=WORK_ANALYSIS_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:analysis.analyze",
            ),
            semantic_validate=lambda candidate: validate_work_analysis_result_v1(
                candidate, context_result=context_result
            ),
        )

    def build_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        context_result: ContextRetrievalResultV1,
    ) -> WorkAnalysisResultV1:
        result = validate_work_analysis_result_v1(
            llm_result.structured_output,
            context_result=context_result,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def invoke_analyze_llm_from_retrieval_result(
        self,
        *,
        request_intent: RequestIntentV2,
        retrieval_result: RetrievalResultV1,
        evidence_drafts: list[EvidenceDraftV1],
        request: WorkflowStartRequest,
        policy_confirmation_receipt_refs: list[str],
        confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    ) -> StructuredLLMResult:
        """SIX_ROLE_BASELINE product runtime entry point (Q2-HANDOFF cleanup).

        Feeds ``analyze.md`` from ``RetrievalResultV1`` + the run's resolved
        ``RunScopedEvidenceStore`` projection directly -- no ``ContextRetrievalResultV1``
        is constructed or received here. ``invoke_analyze_llm`` (above) stays the
        entry point for THREE_STAGE/SINGLE_BASELINE/Evaluation-harness callers,
        which have their own real, LLM-fused or replay-derived
        ``ContextRetrievalResultV1`` and are out of this migration's scope.

        ``confirmation_response`` is only present on a same-owner nested-checkpoint
        resume (C4) -- this is the one Product Prompt NEEDS_CONFIRMATION actually
        originates from, so it is the only one that needs to see the bounded answer.
        """
        prompt_input: dict[str, object] = {
            "user_request": request.request_text,
            "request_intent": request_intent,
            "evidence": _planning_evidence_projection(evidence_drafts),
            "availability_results": [],
            "policy_confirmation_receipt_refs": list(policy_confirmation_receipt_refs),
        }
        if confirmation_response is not None:
            prompt_input["confirmation_response"] = dict(confirmation_response)
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._analyze_prompt_ref,
            prompt_input=prompt_input,
            output_schema=WORK_ANALYSIS_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:analysis.analyze",
            ),
            semantic_validate=(
                lambda candidate: validate_work_analysis_result_v1_from_retrieval_result(
                    candidate,
                    retrieval_result=retrieval_result,
                    evidence_drafts=evidence_drafts,
                )
            ),
        )

    def build_output_from_llm_result_from_retrieval_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        retrieval_result: RetrievalResultV1,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> WorkAnalysisResultV1:
        result = validate_work_analysis_result_v1_from_retrieval_result(
            llm_result.structured_output,
            retrieval_result=retrieval_result,
            evidence_drafts=evidence_drafts,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def build_state_update(self, result: WorkAnalysisResultV1) -> GraphStateUpdateV1:
        phase = (
            WorkflowPhase.SOLUTION_PLANNING
            if AnalysisResult(result["status"]) is AnalysisResult.COMPLETE
            else WorkflowPhase.WORK_ANALYSIS
        )
        return {
            "analysis_result": result,
            "workflow_phase": phase.value,
            "trace_context": {
                "analysis_result": result["status"],
                "finding_count": len(result["findings"]),
                "missing_information_count": len(result["missing_information"]),
                "blocker_count": len(result["blockers"]),
            },
        }


def validate_work_analysis_result_v1(
    value: object,
    *,
    context_result: ContextRetrievalResultV1,
) -> WorkAnalysisResultV1:
    """THREE_STAGE/SINGLE_BASELINE/Evaluation-harness entry point.

    Reference space is scraped off a real (LLM-fused or replay-derived)
    ``ContextRetrievalResultV1``. SIX_ROLE_BASELINE product runtime never
    calls this -- see ``validate_work_analysis_result_v1_from_retrieval_result``.
    """
    return _validate_work_analysis_result_v1_core(value, refs=_reference_space(context_result))


def validate_work_analysis_result_v1_from_retrieval_result(
    value: object,
    *,
    retrieval_result: RetrievalResultV1,
    evidence_drafts: list[EvidenceDraftV1],
) -> WorkAnalysisResultV1:
    """SIX_ROLE_BASELINE product runtime entry point (Q2-HANDOFF cleanup).

    Reference space is derived directly from the canonical ``RetrievalResultV1``
    and its ``RunScopedEvidenceStore``-resolved evidence -- no
    ``ContextRetrievalResultV1`` is built or consumed.
    """
    return _validate_work_analysis_result_v1_core(
        value,
        refs=_reference_space_from_retrieval_result(retrieval_result, evidence_drafts),
    )


def _validate_work_analysis_result_v1_core(
    value: object,
    *,
    refs: _ReferenceSpace,
) -> WorkAnalysisResultV1:
    root = _require_mapping(value, "$")
    _require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "status",
            "summary",
            "findings",
            "missing_information",
            "confirmation",
            "blockers",
            "evidence_refs",
            "resource_refs",
            "segment_refs",
        },
        optional={"llm_provider_result", "schedule_constraints"},
    )
    _require_schema_version(root, "$", WORK_ANALYSIS_SCHEMA_VERSION)
    status = _require_string(root, "status", "$")
    if status not in _ANALYSIS_RESULT_VALUES:
        raise WorkAnalysisValidationError("$.status is invalid")
    findings = [
        _validate_analysis_finding(item, f"$.findings[{index}]", refs)
        for index, item in enumerate(_require_list(root["findings"], "$.findings"))
    ]
    _validate_unique_finding_ids(findings)
    missing_information = _require_string_list(
        root["missing_information"],
        "$.missing_information",
    )
    evidence_refs = _validated_evidence_refs(root["evidence_refs"], refs)
    result: WorkAnalysisResultV1 = {
        "schema_version": 1,
        "status": cast(AnalysisStatusValue, status),
        "summary": _require_string(root, "summary", "$"),
        "findings": findings,
        "missing_information": missing_information,
        "confirmation": _nullable_mapping(root["confirmation"], "$.confirmation"),
        "blockers": _require_string_list(root["blockers"], "$.blockers"),
        "evidence_refs": evidence_refs,
        "resource_refs": _validated_resource_ref_objects(root["resource_refs"], refs),
        "segment_refs": _validated_segment_ref_objects(root["segment_refs"], refs),
        "additional_acquisition_request": _build_additional_acquisition_request(
            status=cast(AnalysisStatusValue, status),
            findings=findings,
            missing_information=missing_information,
            evidence_refs=evidence_refs,
        ),
    }
    if "llm_provider_result" in root:
        result["llm_provider_result"] = _require_mapping(
            root["llm_provider_result"],
            "$.llm_provider_result",
        )
    if "schedule_constraints" in root:
        result["schedule_constraints"] = _validate_schedule_constraints(
            root["schedule_constraints"]
        )
    _validate_result_invariant(result)
    return result


def _validate_schedule_constraints(value: object) -> FeasibilityScheduleConstraintsV1:
    item = _require_mapping(value, "$.schedule_constraints")
    _require_allowed_keys(
        item,
        "$.schedule_constraints",
        required={
            "business_deadline",
            "business_deadline_source",
            "expected_duration_minutes",
            "duration_source",
        },
        optional=set(),
    )
    deadline = _require_string(item, "business_deadline", "$.schedule_constraints")
    try:
        if len(deadline) == 10:
            date.fromisoformat(deadline)
        else:
            parsed_deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if parsed_deadline.tzinfo is None or parsed_deadline.utcoffset() is None:
                raise ValueError
    except ValueError as error:
        raise WorkAnalysisValidationError(
            "business_deadline must be an ISO date or timezone-aware datetime"
        ) from error
    source = _require_string(item, "business_deadline_source", "$.schedule_constraints")
    duration_source = _require_string(item, "duration_source", "$.schedule_constraints")
    if source not in {"USER", "GMAIL_EVIDENCE"}:
        raise WorkAnalysisValidationError("business_deadline_source is invalid")
    if duration_source not in {"EXPLICIT_ESTIMATE", "EVENT_INTERVAL"}:
        raise WorkAnalysisValidationError("duration_source is invalid")
    duration = item["expected_duration_minutes"]
    if duration is not None and (
        not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0
    ):
        raise WorkAnalysisValidationError("expected_duration_minutes must be positive or null")
    return {
        "business_deadline": deadline,
        "business_deadline_source": cast(Literal["USER", "GMAIL_EVIDENCE"], source),
        "expected_duration_minutes": cast(int | None, duration),
        "duration_source": cast(Literal["EXPLICIT_ESTIMATE", "EVENT_INTERVAL"], duration_source),
    }


def build_work_analysis_clarification_question(
    *,
    result: WorkAnalysisResultV1,
    request_intent: RequestIntentV2,
) -> ClarificationQuestionV1:
    confirmation = _require_mapping(result["confirmation"], "$.confirmation")
    return build_clarification_question_v1(
        origin_target="analysis.analyze",
        question=_require_string(confirmation, "question", "$.confirmation"),
        reason_code=_require_string(confirmation, "reason_code", "$.confirmation"),
        known_context_summary=request_intent["goal"],
        affected_field_paths=_optional_string_list(confirmation.get("affected_field_paths")),
        options=_optional_option_list(confirmation.get("options")),
    )


def load_work_analysis_analyze_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "work_analysis.analyze",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def _validate_analysis_finding(
    value: object,
    path: str,
    refs: _ReferenceSpace,
) -> AnalysisFindingV1:
    finding = _require_mapping(value, path)
    _require_allowed_keys(
        finding,
        path,
        required={
            "schema_version",
            "finding_id",
            "kind",
            "statement",
            "evidence_refs",
            "resource_refs",
            "segment_refs",
            "related_resource_handles",
            "reason_codes",
        },
        optional=set(),
    )
    _require_schema_version(finding, path, ANALYSIS_FINDING_SCHEMA_VERSION)
    kind = _require_string(finding, "kind", path)
    if kind in _PROHIBITED_FINDING_KINDS:
        raise WorkAnalysisValidationError(f"{path}.kind is not a normal analysis finding")
    if kind not in _FINDING_KIND_VALUES:
        raise WorkAnalysisValidationError(f"{path}.kind is invalid")
    reason_codes = _require_string_list(finding["reason_codes"], f"{path}.reason_codes")
    if _PROHIBITED_REASON_CODES.intersection(reason_codes):
        raise WorkAnalysisValidationError(f"{path}.reason_codes contains failure taxonomy")
    evidence_refs = _validated_evidence_refs(finding["evidence_refs"], refs, path=path)
    if not evidence_refs:
        raise WorkAnalysisValidationError(f"{path}.evidence_refs must not be empty")
    return {
        "schema_version": 1,
        "finding_id": _require_string(finding, "finding_id", path),
        "kind": cast(AnalysisFindingKind, kind),
        "statement": _require_string(finding, "statement", path),
        "evidence_refs": evidence_refs,
        "resource_refs": _validated_string_refs(
            finding["resource_refs"],
            refs["resource_handles"],
            f"{path}.resource_refs",
            "resource",
        ),
        "segment_refs": _validated_string_refs(
            finding["segment_refs"],
            refs["segment_ids"],
            f"{path}.segment_refs",
            "segment",
        ),
        "related_resource_handles": _validated_string_refs(
            finding["related_resource_handles"],
            refs["resource_handles"],
            f"{path}.related_resource_handles",
            "resource",
        ),
        "reason_codes": reason_codes,
    }


def _validate_unique_finding_ids(findings: list[AnalysisFindingV1]) -> None:
    seen: set[str] = set()
    for finding in findings:
        finding_id = finding["finding_id"]
        if finding_id in seen:
            raise WorkAnalysisValidationError(f"duplicate finding_id: {finding_id}")
        seen.add(finding_id)


def _validate_result_invariant(result: WorkAnalysisResultV1) -> None:
    status = AnalysisResult(result["status"])
    schedule = result.get("schedule_constraints")
    if (
        schedule is not None
        and schedule["duration_source"] == "EXPLICIT_ESTIMATE"
        and schedule["expected_duration_minutes"] is None
        and status is not AnalysisResult.NEEDS_CONFIRMATION
    ):
        raise WorkAnalysisValidationError(
            "$.schedule_constraints.expected_duration_minutes missing expected duration "
            "requires NEEDS_CONFIRMATION"
        )
    if status is AnalysisResult.COMPLETE:
        if result["missing_information"]:
            raise WorkAnalysisValidationError(
                "$.missing_information COMPLETE must not include missing_information"
            )
        if result["confirmation"] is not None:
            raise WorkAnalysisValidationError(
                "$.confirmation COMPLETE must not include confirmation"
            )
        if result["blockers"]:
            raise WorkAnalysisValidationError("$.blockers COMPLETE must not include blockers")
    if status is AnalysisResult.NEEDS_MORE_DATA and not result["missing_information"]:
        raise WorkAnalysisValidationError(
            "$.missing_information NEEDS_MORE_DATA requires missing_information"
        )
    if (
        status is AnalysisResult.ROUTE_RECONSIDERATION_REQUIRED
        and not result["missing_information"]
    ):
        raise WorkAnalysisValidationError(
            "$.missing_information ROUTE_RECONSIDERATION_REQUIRED requires missing_information"
        )
    if status is AnalysisResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise WorkAnalysisValidationError("$.confirmation NEEDS_CONFIRMATION requires confirmation")
    if status is AnalysisResult.BLOCKED and not result["blockers"]:
        raise WorkAnalysisValidationError("$.blockers BLOCKED requires blockers")
    if (
        status is AnalysisResult.NEEDS_MORE_DATA
        and result["additional_acquisition_request"] is None
    ):
        raise WorkAnalysisValidationError(
            "$.additional_acquisition_request NEEDS_MORE_DATA requires "
            "additional_acquisition_request"
        )
    if (
        status is not AnalysisResult.NEEDS_MORE_DATA
        and result["additional_acquisition_request"] is not None
    ):
        raise WorkAnalysisValidationError(
            "$.additional_acquisition_request is only allowed for NEEDS_MORE_DATA"
        )


def _build_additional_acquisition_request(
    *,
    status: AnalysisStatusValue,
    findings: list[AnalysisFindingV1],
    missing_information: list[str],
    evidence_refs: list[str],
) -> AdditionalAcquisitionRequestV1 | None:
    if status != AnalysisResult.NEEDS_MORE_DATA.value:
        return None
    reason_codes = _merged_reason_codes(findings)
    return validate_additional_acquisition_request_v1(
        {
            "schema_version": 1,
            "origin_phase": WorkflowPhase.WORK_ANALYSIS.value,
            "origin_result": AdditionalAcquisitionOriginResult.NEEDS_MORE_DATA.value,
            "missing_slots": [],
            "missing_information": list(missing_information),
            "evidence_refs": list(evidence_refs),
            "reason_codes": reason_codes,
        },
        allowed_evidence_refs=set(evidence_refs),
    )


def _merged_reason_codes(findings: list[AnalysisFindingV1]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for finding in findings:
        for code in finding["reason_codes"]:
            if code in seen:
                continue
            seen.add(code)
            merged.append(code)
    return merged


class _ReferenceSpace(TypedDict):
    evidence_ids: set[str]
    resource_handles: set[str]
    segment_ids: set[str]


def _reference_space(context_result: ContextRetrievalResultV1) -> _ReferenceSpace:
    context_bundle = context_result["context_bundle"]
    evidence_ids = {draft["evidence_id"] for draft in context_result["evidence_drafts"]}
    evidence_ids.update(context_bundle["evidence_refs"])
    return {
        "evidence_ids": evidence_ids,
        "resource_handles": {
            str(ref["resource_handle"])
            for ref in context_bundle["resource_refs"]
            if isinstance(ref.get("resource_handle"), str)
        },
        "segment_ids": {
            str(ref["segment_id"])
            for ref in context_bundle["segment_refs"]
            if isinstance(ref.get("segment_id"), str)
        },
    }


def _reference_space_from_retrieval_result(
    retrieval_result: RetrievalResultV1,
    evidence_drafts: list[EvidenceDraftV1],
) -> _ReferenceSpace:
    evidence_ids = {draft["evidence_id"] for draft in evidence_drafts}
    evidence_ids.update(retrieval_result["evidence_refs"])
    return {
        "evidence_ids": evidence_ids,
        "resource_handles": set(retrieval_result["source_resource_refs"]),
        "segment_ids": set(retrieval_result["selected_segment_ids"]),
    }


def _validated_evidence_refs(
    value: object,
    refs: _ReferenceSpace,
    *,
    path: str = "$",
) -> list[str]:
    return _validated_string_refs(
        value,
        refs["evidence_ids"],
        f"{path}.evidence_refs",
        "evidence",
    )


def _validated_resource_ref_objects(
    value: object,
    refs: _ReferenceSpace,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, item in enumerate(_require_list(value, "$.resource_refs")):
        ref = _require_mapping(item, f"$.resource_refs[{index}]")
        handle = _require_string(ref, "resource_handle", f"$.resource_refs[{index}]")
        if handle not in refs["resource_handles"]:
            raise WorkAnalysisValidationError(f"resource reference does not exist: {handle}")
        result.append(ref)
    return result


def _validated_segment_ref_objects(
    value: object,
    refs: _ReferenceSpace,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, item in enumerate(_require_list(value, "$.segment_refs")):
        ref = _require_mapping(item, f"$.segment_refs[{index}]")
        segment_id = _require_string(ref, "segment_id", f"$.segment_refs[{index}]")
        if segment_id not in refs["segment_ids"]:
            raise WorkAnalysisValidationError(f"segment reference does not exist: {segment_id}")
        result.append(ref)
    return result


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=WorkAnalysisValidationError)
_nullable_mapping = partial(_schema.nullable_mapping, error_cls=WorkAnalysisValidationError)
_require_allowed_keys = partial(_schema.require_allowed_keys, error_cls=WorkAnalysisValidationError)
_require_int = partial(_schema.require_int, error_cls=WorkAnalysisValidationError)
_require_string = partial(_schema.require_string, error_cls=WorkAnalysisValidationError)
_require_list = partial(_schema.require_list, error_cls=WorkAnalysisValidationError)
_require_string_list = partial(_schema.require_string_list, error_cls=WorkAnalysisValidationError)
_require_schema_version = partial(
    _schema.require_schema_version, error_cls=WorkAnalysisValidationError
)
_optional_string_list = partial(_schema.optional_string_list, error_cls=WorkAnalysisValidationError)
_optional_option_list = partial(_schema.optional_option_list, error_cls=WorkAnalysisValidationError)
_validated_string_refs = partial(
    _schema.validated_string_refs, error_cls=WorkAnalysisValidationError
)
_provider_summary = _schema.provider_summary


__all__ = [
    "ANALYSIS_FINDING_SCHEMA_VERSION",
    "WORK_ANALYSIS_OUTPUT_SCHEMA",
    "WORK_ANALYSIS_SCHEMA_VERSION",
    "AnalysisFindingV1",
    "build_work_analysis_clarification_question",
    "WorkAnalysisAgent",
    "WorkAnalysisResultV1",
    "WorkAnalysisValidationError",
    "load_work_analysis_analyze_prompt_reference",
    "validate_work_analysis_result_v1",
    "validate_work_analysis_result_v1_from_retrieval_result",
]
