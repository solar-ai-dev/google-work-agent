"""Work analysis workflow node implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.context_retrieval import ContextRetrievalResultV1
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    AnalysisResult,
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
AnalysisStatusValue = Literal["COMPLETE", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "BLOCKED"]
AnalysisFindingKind = Literal[
    "FACT",
    "RELATIONSHIP",
    "MISSING_INFORMATION",
    "DUPLICATE_CANDIDATE",
    "CONFLICT",
    "SCHEDULE_RISK",
    "EVIDENCE_GAP",
]


class AnalysisFindingV1(TypedDict):
    schema_version: Required[Literal[1]]
    finding_id: str
    kind: AnalysisFindingKind
    statement: str
    evidence_refs: list[str]
    resource_refs: list[str]
    segment_refs: list[str]
    related_resource_handles: list[str]
    reason_codes: list[str]


class WorkAnalysisResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: AnalysisStatusValue
    summary: str
    findings: list[AnalysisFindingV1]
    missing_information: list[str]
    confirmation: dict[str, object] | None
    blockers: list[str]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    segment_refs: list[dict[str, object]]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    llm_provider_result: NotRequired[dict[str, object]]


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
                "enum": ["COMPLETE", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "BLOCKED"],
            },
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "confirmation": {},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "resource_refs": {"type": "array", "items": {"type": "object"}},
            "segment_refs": {"type": "array", "items": {"type": "object"}},
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
        llm_runtime: LLMRuntimeService,
        analyze_prompt_ref: PromptReference | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._analyze_prompt_ref = (
            analyze_prompt_ref or load_work_analysis_analyze_prompt_reference()
        )

    def analyze(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        request: WorkflowStartRequest,
    ) -> WorkAnalysisResultV1:
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._analyze_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "request_intent": request_intent,
                "context_status": context_result["status"],
                "context_bundle": context_result["context_bundle"],
                "evidence_drafts": context_result["evidence_drafts"],
                "selected_segment_ids": list(context_result["selected_segment_ids"]),
                "missing_slots": list(context_result["missing_slots"]),
                "sufficiency": dict(context_result["sufficiency"]),
                "source_content_is_untrusted": True,
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
        )
        result = validate_work_analysis_result_v1(
            llm_result.structured_output,
            context_result=context_result,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def build_state_update(self, result: WorkAnalysisResultV1) -> JsonObject:
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
        optional={"llm_provider_result"},
    )
    _require_schema_version(root, "$", WORK_ANALYSIS_SCHEMA_VERSION)
    refs = _reference_space(context_result)
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
    _validate_result_invariant(result)
    return result


def build_work_analysis_clarification_question(
    *,
    result: WorkAnalysisResultV1,
    request_intent: RequestIntentV1,
) -> ClarificationQuestionV1:
    confirmation = _require_mapping(result["confirmation"], "$.confirmation")
    return build_clarification_question_v1(
        origin_target="analysis.analyze",
        question=_require_string(confirmation, "question", "$.confirmation"),
        reason_code=_require_string(confirmation, "reason_code", "$.confirmation"),
        known_context_summary=request_intent["goal"]["user_visible_objective"]
        or request_intent["goal"]["summary"],
        affected_field_paths=_optional_string_list(confirmation.get("affected_field_paths")),
        options=_optional_option_list(confirmation.get("options")),
    )


def load_work_analysis_analyze_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "analysis.analyze",
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
    if status is AnalysisResult.COMPLETE:
        if result["missing_information"]:
            raise WorkAnalysisValidationError("COMPLETE must not include missing_information")
        if result["confirmation"] is not None:
            raise WorkAnalysisValidationError("COMPLETE must not include confirmation")
        if result["blockers"]:
            raise WorkAnalysisValidationError("COMPLETE must not include blockers")
    if status is AnalysisResult.NEEDS_MORE_DATA and not result["missing_information"]:
        raise WorkAnalysisValidationError("NEEDS_MORE_DATA requires missing_information")
    if status is AnalysisResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise WorkAnalysisValidationError("NEEDS_CONFIRMATION requires confirmation")
    if status is AnalysisResult.BLOCKED and not result["blockers"]:
        raise WorkAnalysisValidationError("BLOCKED requires blockers")
    if (
        status is AnalysisResult.NEEDS_MORE_DATA
        and result["additional_acquisition_request"] is None
    ):
        raise WorkAnalysisValidationError("NEEDS_MORE_DATA requires additional_acquisition_request")
    if (
        status is not AnalysisResult.NEEDS_MORE_DATA
        and result["additional_acquisition_request"] is not None
    ):
        raise WorkAnalysisValidationError(
            "additional_acquisition_request is only allowed for NEEDS_MORE_DATA"
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


def _validated_string_refs(
    value: object,
    allowed: set[str],
    path: str,
    label: str,
) -> list[str]:
    refs = _require_string_list(value, path)
    for item in refs:
        if item not in allowed:
            raise WorkAnalysisValidationError(f"{label} reference does not exist: {item}")
    return refs


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


def _require_schema_version(value: dict[str, object], path: str, expected: int) -> None:
    schema_version = _require_int(value, "schema_version", path)
    if schema_version != expected:
        raise WorkAnalysisValidationError(f"{path}.schema_version must be {expected}")


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkAnalysisValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise WorkAnalysisValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _nullable_mapping(value: object, path: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _require_mapping(value, path)


def _require_allowed_keys(
    value: dict[str, object],
    path: str,
    *,
    required: set[str],
    optional: set[str],
) -> None:
    actual = set(value)
    missing = required - actual
    extra = actual - required - optional
    if missing:
        raise WorkAnalysisValidationError(f"{path} is missing required fields: {sorted(missing)}")
    if extra:
        raise WorkAnalysisValidationError(f"{path} has unsupported fields: {sorted(extra)}")


def _require_int(value: dict[str, object], field: str, path: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise WorkAnalysisValidationError(f"{path}.{field} must be integer")
    return item


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise WorkAnalysisValidationError(f"{path}.{field} must be string")
    return item


def _require_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkAnalysisValidationError(f"{path} must be an array")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    items = _require_list(value, path)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise WorkAnalysisValidationError(f"{path}[{index}] must be string")
    return cast(list[str], items)


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.list")
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise WorkAnalysisValidationError(f"clarification list entry must be string: {index}")
        result.append(item)
    return result


def _optional_option_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.options")
    return [_require_mapping(item, "$.clarification.options[]") for item in items]


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
]
