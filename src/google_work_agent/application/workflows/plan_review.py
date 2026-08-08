"""Plan review workflow node implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.context_retrieval import ContextRetrievalResultV1
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    ReviewResult,
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
from google_work_agent.application.workflows.solution_planning import (
    ActionPlanDraftV1,
    AnswerDraftV1,
)
from google_work_agent.application.workflows.work_analysis import WorkAnalysisResultV1
from google_work_agent.domain import SignedToolRegistry, build_p0_tool_registry
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]
ReviewStatusValue = Literal["PASS", "REVISE", "RETRIEVE_MORE", "CONFIRM", "BLOCK"]
RecheckStatusValue = Literal["PASS", "BLOCK"]
ReviewTargetValue = Literal["ANSWER", "PLAN"]


class ReviewIssueV1(TypedDict):
    schema_version: Required[Literal[2]]
    issue_id: str
    kind: str
    message: str
    affected_action_ids: list[str]
    affected_field_paths: list[str]
    evidence_refs: list[str]
    resource_refs: list[str]
    reason_codes: list[str]


class PlanReviewResultV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: ReviewStatusValue
    summary: str
    issues: list[ReviewIssueV1]
    confirmation: dict[str, object] | None
    blockers: list[str]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    llm_provider_result: NotRequired[dict[str, object]]


class ToolPolicySummaryV1(TypedDict):
    tool_name: str
    effect_type: str
    approval_requirement: str
    verification_policy: str
    recovery_policy: str
    scope: str
    retryable: bool
    input_schema_version: str
    output_schema_version: str
    registry_version: str
    tool_schema_hash: str


class EvidencePolicySummaryV1(TypedDict):
    minimum_evidence_per_action: int
    update_targeting_requirements: list[str]


class PolicyReviewContextV1(TypedDict):
    schema_version: Required[Literal[1]]
    tool_registry_version: str
    tool_policies: list[ToolPolicySummaryV1]
    evidence_policy: EvidencePolicySummaryV1


PLAN_REVIEW_SCHEMA_VERSION = 2
REVIEW_ISSUE_SCHEMA_VERSION = 2
POLICY_REVIEW_CONTEXT_SCHEMA_VERSION = 1
PLAN_REVIEW_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="plan-review-result-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "summary",
            "issues",
            "confirmation",
            "blockers",
            "additional_acquisition_request",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [PLAN_REVIEW_SCHEMA_VERSION]},
            "status": {
                "type": "string",
                "enum": ["PASS", "REVISE", "RETRIEVE_MORE", "CONFIRM", "BLOCK"],
            },
            "summary": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "schema_version",
                        "issue_id",
                        "kind",
                        "message",
                        "affected_action_ids",
                        "affected_field_paths",
                        "evidence_refs",
                        "resource_refs",
                        "reason_codes",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "schema_version": {
                            "type": "integer",
                            "enum": [REVIEW_ISSUE_SCHEMA_VERSION],
                        },
                        "issue_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "message": {"type": "string"},
                        "affected_action_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "affected_field_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        "resource_refs": {"type": "array", "items": {"type": "string"}},
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "confirmation": {},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "additional_acquisition_request": {},
        },
    },
)

_INSPECT_ALLOWED_STATUSES = frozenset(item.value for item in ReviewResult)
_RECHECK_ALLOWED_STATUSES = frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value})


class PlanReviewValidationError(ValueError):
    """Raised when plan review structured output is invalid."""


class PlanReviewAgent:
    """Inspect or recheck drafts without mutating workflow state."""

    def __init__(
        self,
        *,
        llm_runtime: LLMRuntimeService,
        inspect_prompt_ref: PromptReference | None = None,
        recheck_prompt_ref: PromptReference | None = None,
        tool_registry: SignedToolRegistry | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._inspect_prompt_ref = inspect_prompt_ref or load_plan_review_inspect_prompt_reference(
            manifest_path
        )
        self._recheck_prompt_ref = recheck_prompt_ref or load_plan_review_recheck_prompt_reference(
            manifest_path
        )
        self._tool_registry = tool_registry or build_p0_tool_registry()

    @property
    def inspect_prompt_ref(self) -> PromptReference:
        return self._inspect_prompt_ref

    @property
    def recheck_prompt_ref(self) -> PromptReference:
        return self._recheck_prompt_ref

    def inspect(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
    ) -> PlanReviewResultV1:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        llm_result = self.invoke_inspect_llm(
            request_intent=request_intent,
            context_result=context_result,
            analysis_result=analysis_result,
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            request=request,
            policy_review_context=policy_review_context,
        )
        return self.build_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )

    def invoke_inspect_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
    ) -> StructuredLLMResult:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._inspect_prompt_ref,
            prompt_input=_build_review_prompt_input(
                request=request,
                request_intent=request_intent,
                context_result=context_result,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or build_policy_review_context_v1(tool_registry=self._tool_registry),
            ),
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.inspect",
            ),
        )

    def recheck(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
    ) -> PlanReviewResultV1:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        llm_result = self.invoke_recheck_llm(
            request_intent=request_intent,
            context_result=context_result,
            analysis_result=analysis_result,
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            request=request,
            policy_review_context=policy_review_context,
        )
        return self.build_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            allowed_statuses=_RECHECK_ALLOWED_STATUSES,
        )

    def invoke_recheck_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
    ) -> StructuredLLMResult:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._recheck_prompt_ref,
            prompt_input=_build_review_prompt_input(
                request=request,
                request_intent=request_intent,
                context_result=context_result,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or build_policy_review_context_v1(tool_registry=self._tool_registry),
            ),
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.recheck",
            ),
        )

    def build_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        allowed_statuses: frozenset[str] = _INSPECT_ALLOWED_STATUSES,
    ) -> PlanReviewResultV1:
        target_kind, _draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        result = validate_plan_review_result_v1(
            llm_result.structured_output,
            target_kind=target_kind,
            analysis_result=analysis_result,
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            allowed_statuses=allowed_statuses,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def build_state_update(
        self,
        result: PlanReviewResultV1,
    ) -> JsonObject:
        return {
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
            "plan_review": result,
            "trace_context": {
                "review_result": result["status"],
                "review_issue_count": len(result["issues"]),
                "review_blocker_count": len(result["blockers"]),
            },
        }


def build_policy_review_context_v1(
    *,
    tool_registry: SignedToolRegistry | None = None,
) -> PolicyReviewContextV1:
    registry = tool_registry or build_p0_tool_registry()
    entries = registry.list_entries()
    tool_policies: list[ToolPolicySummaryV1] = [
        {
            "tool_name": entry.tool_name,
            "effect_type": entry.effect_type.value,
            "approval_requirement": entry.approval_requirement.value,
            "verification_policy": entry.verification_policy.value,
            "recovery_policy": entry.recovery_policy.value,
            "scope": entry.scope,
            "retryable": entry.retryable,
            "input_schema_version": entry.input_schema_version,
            "output_schema_version": entry.output_schema_version,
            "registry_version": entry.registry_version,
            "tool_schema_hash": entry.tool_schema_hash,
        }
        for entry in entries
    ]
    registry_version = entries[0].registry_version if entries else ""
    return {
        "schema_version": 1,
        "tool_registry_version": registry_version,
        "tool_policies": tool_policies,
        "evidence_policy": {
            "minimum_evidence_per_action": 1,
            "update_targeting_requirements": [
                "user_selected_resource",
                "two_evidences",
                "explicit_resource_relation",
            ],
        },
    }


def resolve_review_target(
    *,
    answer_draft: AnswerDraftV1 | None,
    plan_draft: ActionPlanDraftV1 | None,
) -> tuple[ReviewTargetValue, AnswerDraftV1 | ActionPlanDraftV1]:
    if answer_draft is None and plan_draft is None:
        raise PlanReviewValidationError("review target is missing")
    if answer_draft is not None and plan_draft is not None:
        raise PlanReviewValidationError("review target requires exactly one draft")
    if answer_draft is not None:
        return "ANSWER", answer_draft
    return "PLAN", cast(ActionPlanDraftV1, plan_draft)


def validate_plan_review_result_v1(
    value: object,
    *,
    target_kind: ReviewTargetValue,
    analysis_result: WorkAnalysisResultV1,
    answer_draft: AnswerDraftV1 | None,
    plan_draft: ActionPlanDraftV1 | None,
    allowed_statuses: frozenset[str] = _INSPECT_ALLOWED_STATUSES,
) -> PlanReviewResultV1:
    root = _require_mapping(value, "$")
    _require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "status",
            "summary",
            "issues",
            "confirmation",
            "blockers",
            "additional_acquisition_request",
        },
        optional={"llm_provider_result"},
    )
    _require_schema_version(root, "$", PLAN_REVIEW_SCHEMA_VERSION)
    status = _require_string(root, "status", "$")
    if status not in allowed_statuses:
        raise PlanReviewValidationError("$.status is invalid")
    refs = _reference_space(analysis_result=analysis_result, plan_draft=plan_draft)
    issues = [
        _validate_review_issue(
            item,
            path=f"$.issues[{index}]",
            target_kind=target_kind,
            refs=refs,
        )
        for index, item in enumerate(_require_list(root["issues"], "$.issues"))
    ]
    _validate_issue_collection(issues)
    result: PlanReviewResultV1 = {
        "schema_version": PLAN_REVIEW_SCHEMA_VERSION,
        "status": cast(ReviewStatusValue, status),
        "summary": _require_string(root, "summary", "$"),
        "issues": issues,
        "confirmation": _nullable_mapping(root["confirmation"], "$.confirmation"),
        "blockers": _require_string_list(root["blockers"], "$.blockers"),
        "additional_acquisition_request": _build_additional_acquisition_request(
            status=cast(ReviewStatusValue, status),
            issues=issues,
            allowed_evidence_refs=refs["evidence_ids"],
        ),
    }
    if "llm_provider_result" in root:
        result["llm_provider_result"] = _require_mapping(
            root["llm_provider_result"],
            "$.llm_provider_result",
        )
    _validate_plan_review_invariant(
        result,
        target_kind=target_kind,
        answer_draft=answer_draft,
        plan_draft=plan_draft,
        allowed_statuses=allowed_statuses,
    )
    return result


def build_plan_review_clarification_question(
    *,
    result: PlanReviewResultV1,
    request_intent: RequestIntentV1,
) -> ClarificationQuestionV1:
    confirmation = _require_mapping(result["confirmation"], "$.confirmation")
    return build_clarification_question_v1(
        origin_target="review.inspect",
        question=_require_string(confirmation, "question", "$.confirmation"),
        reason_code=_require_string(confirmation, "reason_code", "$.confirmation"),
        known_context_summary=request_intent["goal"]["user_visible_objective"]
        or request_intent["goal"]["summary"],
        affected_field_paths=_optional_string_list(confirmation.get("affected_field_paths")),
        options=_optional_option_list(confirmation.get("options")),
    )


def load_plan_review_inspect_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "review.inspect",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_plan_review_recheck_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "review.recheck",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


class _ReferenceSpace(TypedDict):
    evidence_ids: set[str]
    resource_handles: set[str]
    action_ids: set[str]


def _build_review_prompt_input(
    *,
    request: WorkflowStartRequest,
    request_intent: RequestIntentV1,
    context_result: ContextRetrievalResultV1,
    analysis_result: WorkAnalysisResultV1,
    draft: AnswerDraftV1 | ActionPlanDraftV1,
    target_kind: ReviewTargetValue,
    policy_review_context: PolicyReviewContextV1,
) -> JsonObject:
    return {
        "request_text": request.request_text,
        "request_intent": request_intent,
        "review_target": target_kind,
        "draft": draft,
        "context_status": context_result["status"],
        "context_bundle": context_result["context_bundle"],
        "evidence_drafts": context_result["evidence_drafts"],
        "analysis_result": analysis_result,
        "policy_review_context": policy_review_context,
        "source_content_is_untrusted": True,
    }


def _validate_review_issue(
    value: object,
    *,
    path: str,
    target_kind: ReviewTargetValue,
    refs: _ReferenceSpace,
) -> ReviewIssueV1:
    issue = _require_mapping(value, path)
    _require_allowed_keys(
        issue,
        path,
        required={
            "schema_version",
            "issue_id",
            "kind",
            "message",
            "affected_action_ids",
            "affected_field_paths",
            "evidence_refs",
            "resource_refs",
            "reason_codes",
        },
        optional=set(),
    )
    _require_schema_version(issue, path, REVIEW_ISSUE_SCHEMA_VERSION)
    affected_action_ids = _require_string_list(
        issue["affected_action_ids"],
        f"{path}.affected_action_ids",
    )
    if target_kind == "ANSWER" and affected_action_ids:
        raise PlanReviewValidationError(
            f"{path}.affected_action_ids must be empty for answer review target"
        )
    for action_id in affected_action_ids:
        if action_id not in refs["action_ids"]:
            raise PlanReviewValidationError(f"affected action does not exist: {action_id}")
    evidence_refs = _validated_string_refs(
        issue["evidence_refs"],
        refs["evidence_ids"],
        f"{path}.evidence_refs",
        "evidence",
    )
    resource_refs = _validated_string_refs(
        issue["resource_refs"],
        refs["resource_handles"],
        f"{path}.resource_refs",
        "resource",
    )
    return {
        "schema_version": REVIEW_ISSUE_SCHEMA_VERSION,
        "issue_id": _require_string(issue, "issue_id", path),
        "kind": _require_string(issue, "kind", path),
        "message": _require_string(issue, "message", path),
        "affected_action_ids": affected_action_ids,
        "affected_field_paths": _require_string_list(
            issue["affected_field_paths"],
            f"{path}.affected_field_paths",
        ),
        "evidence_refs": evidence_refs,
        "resource_refs": resource_refs,
        "reason_codes": _require_string_list(issue["reason_codes"], f"{path}.reason_codes"),
    }


def _validate_issue_collection(issues: list[ReviewIssueV1]) -> None:
    issue_ids = [issue["issue_id"] for issue in issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise PlanReviewValidationError("duplicate issue_id in review result")


def _validate_plan_review_invariant(
    result: PlanReviewResultV1,
    *,
    target_kind: ReviewTargetValue,
    answer_draft: AnswerDraftV1 | None,
    plan_draft: ActionPlanDraftV1 | None,
    allowed_statuses: frozenset[str],
) -> None:
    resolve_review_target(answer_draft=answer_draft, plan_draft=plan_draft)
    status = ReviewResult(result["status"])
    if status.value not in allowed_statuses:
        raise PlanReviewValidationError("review result is not allowed for this node")
    if status is ReviewResult.PASS:
        if result["issues"]:
            raise PlanReviewValidationError("PASS must not include issues")
        if result["confirmation"] is not None:
            raise PlanReviewValidationError("PASS must not include confirmation")
        if result["blockers"]:
            raise PlanReviewValidationError("PASS must not include blockers")
    if status is ReviewResult.REVISE and not result["issues"]:
        raise PlanReviewValidationError("REVISE requires issues")
    if status is ReviewResult.RETRIEVE_MORE and not result["issues"]:
        raise PlanReviewValidationError("RETRIEVE_MORE requires issues")
    if status is ReviewResult.CONFIRM and result["confirmation"] is None:
        raise PlanReviewValidationError("CONFIRM requires confirmation")
    if status is ReviewResult.BLOCK and not result["blockers"]:
        raise PlanReviewValidationError("BLOCK requires blockers")
    if status is ReviewResult.RETRIEVE_MORE and result["additional_acquisition_request"] is None:
        raise PlanReviewValidationError("RETRIEVE_MORE requires additional_acquisition_request")
    if (
        status is not ReviewResult.RETRIEVE_MORE
        and result["additional_acquisition_request"] is not None
    ):
        raise PlanReviewValidationError(
            "additional_acquisition_request is only allowed for RETRIEVE_MORE"
        )
    if target_kind == "ANSWER":
        for issue in result["issues"]:
            if issue["affected_action_ids"]:
                raise PlanReviewValidationError(
                    "answer review issues must not include affected_action_ids"
                )


def _reference_space(
    *,
    analysis_result: WorkAnalysisResultV1,
    plan_draft: ActionPlanDraftV1 | None,
) -> _ReferenceSpace:
    action_ids = set()
    if plan_draft is not None:
        action_ids = {action["action_id"] for action in plan_draft["actions"]}
    return {
        "evidence_ids": set(analysis_result["evidence_refs"]),
        "resource_handles": {
            str(ref["resource_handle"])
            for ref in analysis_result["resource_refs"]
            if isinstance(ref.get("resource_handle"), str)
        },
        "action_ids": action_ids,
    }


def _build_additional_acquisition_request(
    *,
    status: ReviewStatusValue,
    issues: list[ReviewIssueV1],
    allowed_evidence_refs: set[str],
) -> AdditionalAcquisitionRequestV1 | None:
    if status != ReviewResult.RETRIEVE_MORE.value:
        return None
    try:
        return validate_additional_acquisition_request_v1(
            {
                "schema_version": 1,
                "origin_phase": WorkflowPhase.PLAN_REVIEW.value,
                "origin_result": AdditionalAcquisitionOriginResult.RETRIEVE_MORE.value,
                "missing_slots": [],
                "missing_information": [],
                "evidence_refs": _merge_issue_string_refs(issues, key="evidence_refs"),
                "reason_codes": _merge_issue_string_refs(issues, key="reason_codes"),
            },
            allowed_evidence_refs=allowed_evidence_refs,
        )
    except ValueError as error:
        raise PlanReviewValidationError(str(error)) from error


def _merge_issue_string_refs(
    issues: list[ReviewIssueV1],
    *,
    key: Literal["evidence_refs", "reason_codes"],
) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for issue in issues:
        for item in issue[key]:
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _validated_string_refs(
    value: object,
    allowed: set[str],
    path: str,
    label: str,
) -> list[str]:
    refs = _require_string_list(value, path)
    for item in refs:
        if item not in allowed:
            raise PlanReviewValidationError(f"{label} reference does not exist: {item}")
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
        raise PlanReviewValidationError(f"{path}.schema_version must be {expected}")


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PlanReviewValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlanReviewValidationError(f"{path} keys must be strings")
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
        raise PlanReviewValidationError(f"{path} is missing required fields: {sorted(missing)}")
    if extra:
        raise PlanReviewValidationError(f"{path} has unsupported fields: {sorted(extra)}")


def _require_int(value: dict[str, object], field: str, path: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise PlanReviewValidationError(f"{path}.{field} must be integer")
    return item


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise PlanReviewValidationError(f"{path}.{field} must be string")
    return item


def _require_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise PlanReviewValidationError(f"{path} must be an array")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    items = _require_list(value, path)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise PlanReviewValidationError(f"{path}[{index}] must be string")
    return cast(list[str], items)


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.list")
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise PlanReviewValidationError(f"clarification list entry must be string: {index}")
        result.append(item)
    return result


def _optional_option_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.options")
    return [_require_mapping(item, "$.clarification.options[]") for item in items]


__all__ = [
    "PLAN_REVIEW_OUTPUT_SCHEMA",
    "PLAN_REVIEW_SCHEMA_VERSION",
    "POLICY_REVIEW_CONTEXT_SCHEMA_VERSION",
    "REVIEW_ISSUE_SCHEMA_VERSION",
    "build_plan_review_clarification_question",
    "PlanReviewAgent",
    "PlanReviewResultV1",
    "PlanReviewValidationError",
    "PolicyReviewContextV1",
    "ReviewIssueV1",
    "build_policy_review_context_v1",
    "load_plan_review_inspect_prompt_reference",
    "load_plan_review_recheck_prompt_reference",
    "resolve_review_target",
    "validate_plan_review_result_v1",
]
