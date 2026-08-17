"""Plan review workflow node implementation."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final, Literal, TypedDict, cast

import google_work_agent.application.workflows._schema_support as _schema
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionOriginResult,
    AdditionalAcquisitionRequestV1,
    GraphStateUpdateV1,
    ReviewResult,
    WorkflowPhase,
    validate_additional_acquisition_request_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    ClarificationQuestionV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    PlanReviewResultV1,
    PolicyReviewContextV1,
    RequestIntentV2,
    ReviewIssueV1,
    ReviewStatusValue,
    ReviewTargetValue,
    ToolPolicySummaryV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    EvidencePolicySummaryV1 as EvidencePolicySummaryV1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    RecheckStatusValue as RecheckStatusValue,
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
from google_work_agent.domain import SignedToolRegistry, build_p0_tool_registry
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    ToolCallProviderResponse,
    ToolDefinition,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]
PLAN_REVIEW_SCHEMA_VERSION: Final = 2
REVIEW_ISSUE_SCHEMA_VERSION: Final = 2
POLICY_REVIEW_CONTEXT_SCHEMA_VERSION: Final = 1
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
                "enum": [
                    "PASS",
                    "REVISE",
                    "RETRIEVE_MORE",
                    "ROUTE_RECONSIDERATION",
                    "CONFIRM",
                    "BLOCK",
                ],
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
            "confirmation": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "string"}},
            # additional_acquisition_request is not produced by the LLM: the
            # server always overwrites it via _build_additional_acquisition_request
            # below, using status/issues already validated separately. Its
            # raw LLM-provided value is discarded either way, so this stays
            # deliberately unconstrained rather than adding a schema-shape
            # failure mode for a value nothing ever reads.
            "additional_acquisition_request": {},
        },
    },
)

_INSPECT_ALLOWED_STATUSES = frozenset(item.value for item in ReviewResult)
_RECHECK_ALLOWED_STATUSES = frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value})

_REVIEW_ISSUE_PARAMETER_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "issue_id": {"type": "string"},
        "kind": {"type": "string"},
        "message": {"type": "string"},
        "affected_action_ids": {"type": "array", "items": {"type": "string"}},
        "affected_field_paths": {"type": "array", "items": {"type": "string"}},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "resource_refs": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "issue_id",
        "kind",
        "message",
        "affected_action_ids",
        "affected_field_paths",
        "evidence_refs",
        "resource_refs",
        "reason_codes",
    ],
}

# Native Tool-Calling discriminated functions for review.inspect/review.recheck.
# The function NAME is the status discriminator -- status is never an
# argument, so e.g. review_pass has no confirmation parameter at all and
# "PASS + confirmation" cannot be expressed, let alone generated.
REVIEW_PASS_TOOL: Final = ToolDefinition(
    name="review_pass",
    description=(
        "The plan/answer fully satisfies user scope, evidence grounding, "
        "Tool/effect/target correctness, argument constraints, and DAG "
        "integrity. Has no issues, no confirmation, and no blockers."
    ),
    parameters={
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
)
REVIEW_REVISE_TOOL: Final = ToolDefinition(
    name="review_revise",
    description="Local plan/answer errors exist that Planning can correct from existing evidence.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": _REVIEW_ISSUE_PARAMETER_SCHEMA},
        },
        "required": ["summary", "issues"],
    },
)
REVIEW_RETRIEVE_MORE_TOOL: Final = ToolDefinition(
    name="review_retrieve_more",
    description="Required evidence is absent and cannot be repaired from the current context.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": _REVIEW_ISSUE_PARAMETER_SCHEMA},
        },
        "required": ["summary", "issues"],
    },
)
REVIEW_ROUTE_RECONSIDERATION_TOOL: Final = ToolDefinition(
    name="review_route_reconsideration",
    description=(
        "The fixed route cannot satisfy the request; a different Resource/Connector route "
        "is needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": _REVIEW_ISSUE_PARAMETER_SCHEMA},
        },
        "required": ["summary", "issues"],
    },
)
REVIEW_CONFIRM_TOOL: Final = ToolDefinition(
    name="review_confirm",
    description=(
        "The user must choose among meaningful targets or supply a required "
        "value before this can proceed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "confirmation": {"type": "object"},
        },
        "required": ["summary", "confirmation"],
    },
)
REVIEW_BLOCK_TOOL: Final = ToolDefinition(
    name="review_block",
    description=(
        "The requested operation is truly prohibited, or the same semantic "
        "failure has exhausted its revision budget."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "blockers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "blockers"],
    },
)
_REVIEW_FUNCTION_TO_STATUS: Final = {
    "review_pass": ReviewResult.PASS.value,
    "review_revise": ReviewResult.REVISE.value,
    "review_retrieve_more": ReviewResult.RETRIEVE_MORE.value,
    "review_route_reconsideration": ReviewResult.ROUTE_RECONSIDERATION.value,
    "review_confirm": ReviewResult.CONFIRM.value,
    "review_block": ReviewResult.BLOCK.value,
}
REVIEW_INSPECT_TOOLS: Final = (
    REVIEW_PASS_TOOL,
    REVIEW_REVISE_TOOL,
    REVIEW_RETRIEVE_MORE_TOOL,
    REVIEW_ROUTE_RECONSIDERATION_TOOL,
    REVIEW_CONFIRM_TOOL,
    REVIEW_BLOCK_TOOL,
)
REVIEW_RECHECK_TOOLS: Final = (REVIEW_PASS_TOOL, REVIEW_BLOCK_TOOL)


def _review_tool_call_to_result_v1(response: ToolCallProviderResponse) -> dict[str, object]:
    """Deterministic Application-layer mapping: native tool call -> ``PlanReviewResultV1``.

    The Ollama adapter never sees this function -- it only returns generic
    ``name``/``arguments`` pairs. Raises ``ValueError`` for every invalid
    tool-call shape (0 calls, 2+ calls, unknown function, malformed
    arguments); the runtime treats that exactly like a shape failure and
    shares the same one-attempt repair budget.
    """
    if len(response.calls) != 1:
        raise ValueError(f"expected exactly one review tool call, got {len(response.calls)}")
    call = response.calls[0]
    status = _REVIEW_FUNCTION_TO_STATUS.get(call.name)
    if status is None:
        raise ValueError(f"unknown review function: {call.name}")
    arguments = call.arguments
    summary = arguments.get("summary")
    if not isinstance(summary, str):
        raise ValueError(f"{call.name} arguments.summary must be a string")

    issues: list[dict[str, object]] = []
    if call.name in ("review_revise", "review_retrieve_more", "review_route_reconsideration"):
        raw_issues = arguments.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError(f"{call.name} arguments.issues must be a list")
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                raise ValueError(f"{call.name} arguments.issues item must be an object")
            issues.append({"schema_version": REVIEW_ISSUE_SCHEMA_VERSION, **raw_issue})

    confirmation: dict[str, object] | None = None
    if call.name == "review_confirm":
        raw_confirmation = arguments.get("confirmation")
        if not isinstance(raw_confirmation, dict):
            raise ValueError("review_confirm arguments.confirmation must be an object")
        confirmation = dict(raw_confirmation)

    blockers: list[str] = []
    if call.name == "review_block":
        raw_blockers = arguments.get("blockers")
        if not isinstance(raw_blockers, list) or not all(
            isinstance(item, str) for item in raw_blockers
        ):
            raise ValueError("review_block arguments.blockers must be a list of strings")
        blockers = list(raw_blockers)

    return {
        "schema_version": PLAN_REVIEW_SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "issues": issues,
        "confirmation": confirmation,
        "blockers": blockers,
        # Always server-computed later, exactly like the free-JSON path (see
        # PLAN_REVIEW_OUTPUT_SCHEMA's additional_acquisition_request comment).
        "additional_acquisition_request": None,
    }


class PlanReviewValidationError(ValueError):
    """Raised when plan review structured output is invalid."""


class PlanReviewAgent:
    """Inspect or recheck drafts without mutating workflow state."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
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
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
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
            deterministic_action_risks=deterministic_action_risks,
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
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
    ) -> StructuredLLMResult:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_tool_call(
            prompt_ref=self._inspect_prompt_ref,
            prompt_input=_build_review_prompt_input(
                request=request,
                request_intent=request_intent,
                context_result=context_result,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or _shortlisted_policy_review_context_v1(
                    tool_registry=self._tool_registry, target_kind=target_kind, draft=draft
                ),
                deterministic_action_risks=deterministic_action_risks,
            ),
            tools=REVIEW_INSPECT_TOOLS,
            mapper=_review_tool_call_to_result_v1,
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.inspect",
            ),
            semantic_validate=lambda candidate: validate_plan_review_result_v1(
                candidate,
                target_kind=target_kind,
                analysis_result=analysis_result,
                answer_draft=answer_draft,
                plan_draft=plan_draft,
            ),
        )

    def invoke_inspect_llm_from_evidence(
        self,
        *,
        request_intent: RequestIntentV2,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
    ) -> StructuredLLMResult:
        """SIX_ROLE_BASELINE product runtime entry point (Q2-HANDOFF cleanup).

        Feeds ``review.inspect.md`` from the run's resolved
        ``RunScopedEvidenceStore`` projection directly -- no
        ``ContextRetrievalResultV1`` is constructed or received here.
        ``invoke_inspect_llm`` (above) stays the entry point for
        THREE_STAGE/SINGLE_BASELINE, out of this migration's scope.
        Validation is unaffected: ``validate_plan_review_result_v1``'s
        reference space is scraped off ``analysis_result``/``plan_draft``,
        never off context.
        """
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_tool_call(
            prompt_ref=self._inspect_prompt_ref,
            prompt_input=_build_review_prompt_input_from_evidence(
                request=request,
                request_intent=request_intent,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or _shortlisted_policy_review_context_v1(
                    tool_registry=self._tool_registry, target_kind=target_kind, draft=draft
                ),
                deterministic_action_risks=deterministic_action_risks,
            ),
            tools=REVIEW_INSPECT_TOOLS,
            mapper=_review_tool_call_to_result_v1,
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.inspect",
            ),
            semantic_validate=lambda candidate: validate_plan_review_result_v1(
                candidate,
                target_kind=target_kind,
                analysis_result=analysis_result,
                answer_draft=answer_draft,
                plan_draft=plan_draft,
            ),
        )

    def recheck(
        self,
        *,
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
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
            deterministic_action_risks=deterministic_action_risks,
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
        request_intent: RequestIntentV2,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
    ) -> StructuredLLMResult:
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_tool_call(
            prompt_ref=self._recheck_prompt_ref,
            prompt_input=_build_review_prompt_input(
                request=request,
                request_intent=request_intent,
                context_result=context_result,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or _shortlisted_policy_review_context_v1(
                    tool_registry=self._tool_registry, target_kind=target_kind, draft=draft
                ),
                deterministic_action_risks=deterministic_action_risks,
            ),
            tools=REVIEW_RECHECK_TOOLS,
            mapper=_review_tool_call_to_result_v1,
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.recheck",
            ),
            semantic_validate=lambda candidate: validate_plan_review_result_v1(
                candidate,
                target_kind=target_kind,
                analysis_result=analysis_result,
                answer_draft=answer_draft,
                plan_draft=plan_draft,
                allowed_statuses=_RECHECK_ALLOWED_STATUSES,
            ),
        )

    def invoke_recheck_llm_from_evidence(
        self,
        *,
        request_intent: RequestIntentV2,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1,
        answer_draft: AnswerDraftV1 | None,
        plan_draft: ActionPlanDraftV1 | None,
        request: WorkflowStartRequest,
        policy_review_context: PolicyReviewContextV1 | None = None,
        deterministic_action_risks: dict[str, dict[str, object]] | None = None,
    ) -> StructuredLLMResult:
        """SIX_ROLE_BASELINE product runtime entry point (Q2-HANDOFF cleanup).

        See ``invoke_inspect_llm_from_evidence`` docstring.
        """
        target_kind, draft = resolve_review_target(
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        return self._llm_runtime.invoke_tool_call(
            prompt_ref=self._recheck_prompt_ref,
            prompt_input=_build_review_prompt_input_from_evidence(
                request=request,
                request_intent=request_intent,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                draft=draft,
                target_kind=target_kind,
                policy_review_context=policy_review_context
                or _shortlisted_policy_review_context_v1(
                    tool_registry=self._tool_registry, target_kind=target_kind, draft=draft
                ),
                deterministic_action_risks=deterministic_action_risks,
            ),
            tools=REVIEW_RECHECK_TOOLS,
            mapper=_review_tool_call_to_result_v1,
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.recheck",
            ),
            semantic_validate=lambda candidate: validate_plan_review_result_v1(
                candidate,
                target_kind=target_kind,
                analysis_result=analysis_result,
                answer_draft=answer_draft,
                plan_draft=plan_draft,
                allowed_statuses=_RECHECK_ALLOWED_STATUSES,
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
    ) -> GraphStateUpdateV1:
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


def _shortlisted_policy_review_context_v1(
    *,
    tool_registry: SignedToolRegistry,
    target_kind: ReviewTargetValue,
    draft: AnswerDraftV1 | ActionPlanDraftV1,
) -> PolicyReviewContextV1:
    """Deterministic, registry-derived ``tool_policies`` shortlist for review.inspect/recheck.

    ``build_policy_review_context_v1`` always includes every registered
    tool's full policy summary (all P0 tools today), which the free-JSON
    ``invoke_structured`` path tolerates fine but which overwhelms native
    Tool Calling: empirically, qwen2.5:7b reliably calls a review function
    with a shortlisted ~1-3 tool policy list, but reliably calls *no*
    function at all once the full ~19-tool policy block is present in the
    same turn (confirmed via isolated real-model probes). Only the tools
    actually referenced by the draft under review are relevant to Rule 1's
    "Tool/effect/target correctness" check, so nothing the reviewer needs
    is dropped -- the source of truth is still ``tool_registry.list_entries()``,
    never a hardcoded tool-name list, and the deterministic
    ``validate_plan_review_result_v1``/registry checks are unaffected either
    way since they run in Python against the real registry regardless of
    what subset the model saw.
    """
    referenced_tool_names: set[str] = set()
    if target_kind == "PLAN":
        for action in cast(ActionPlanDraftV1, draft)["actions"]:
            referenced_tool_names.add(action["tool_name"])
    full_context = build_policy_review_context_v1(tool_registry=tool_registry)
    return {
        **full_context,
        "tool_policies": [
            policy
            for policy in full_context["tool_policies"]
            if policy["tool_name"] in referenced_tool_names
        ],
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
    request_intent: RequestIntentV2,
) -> ClarificationQuestionV1:
    confirmation = _require_mapping(result["confirmation"], "$.confirmation")
    return build_clarification_question_v1(
        origin_target="review.inspect",
        question=_require_string(confirmation, "question", "$.confirmation"),
        reason_code=_require_string(confirmation, "reason_code", "$.confirmation"),
        known_context_summary=request_intent["goal"],
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
        "review.inspect.recheck",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


class _ReferenceSpace(TypedDict):
    evidence_ids: set[str]
    resource_handles: set[str]
    action_ids: set[str]


def _build_review_prompt_input(
    *,
    request: WorkflowStartRequest,
    request_intent: RequestIntentV2,
    context_result: ContextRetrievalResultV1,
    analysis_result: WorkAnalysisResultV1,
    draft: AnswerDraftV1 | ActionPlanDraftV1,
    target_kind: ReviewTargetValue,
    policy_review_context: PolicyReviewContextV1,
    deterministic_action_risks: dict[str, dict[str, object]] | None = None,
) -> JsonObject:
    prompt_input: JsonObject = {
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
    if deterministic_action_risks is not None:
        prompt_input["deterministic_action_risks"] = deterministic_action_risks
    return prompt_input


def _build_review_prompt_input_from_evidence(
    *,
    request: WorkflowStartRequest,
    request_intent: RequestIntentV2,
    evidence_drafts: list[EvidenceDraftV1],
    analysis_result: WorkAnalysisResultV1,
    draft: AnswerDraftV1 | ActionPlanDraftV1,
    target_kind: ReviewTargetValue,
    policy_review_context: PolicyReviewContextV1,
    deterministic_action_risks: dict[str, dict[str, object]] | None = None,
) -> JsonObject:
    """SIX_ROLE_BASELINE product runtime prompt input (Q2-HANDOFF cleanup).

    Intent + plan/answer draft + bounded evidence/policy projection only --
    no ``ContextRetrievalResultV1``-shaped ``context_status``/``context_bundle``.
    """
    prompt_input: JsonObject = {
        "request_text": request.request_text,
        "request_intent": request_intent,
        "review_target": target_kind,
        "draft": draft,
        "evidence_drafts": list(evidence_drafts),
        "analysis_result": analysis_result,
        "policy_review_context": policy_review_context,
        "source_content_is_untrusted": True,
    }
    if deterministic_action_risks is not None:
        prompt_input["deterministic_action_risks"] = deterministic_action_risks
    return prompt_input


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
            raise PlanReviewValidationError("$.issues PASS must not include issues")
        if result["confirmation"] is not None:
            raise PlanReviewValidationError("$.confirmation PASS must not include confirmation")
        if result["blockers"]:
            raise PlanReviewValidationError("$.blockers PASS must not include blockers")
    if status is ReviewResult.REVISE and not result["issues"]:
        raise PlanReviewValidationError("$.issues REVISE requires issues")
    if status is ReviewResult.RETRIEVE_MORE and not result["issues"]:
        raise PlanReviewValidationError("$.issues RETRIEVE_MORE requires issues")
    if status is ReviewResult.ROUTE_RECONSIDERATION and not result["issues"]:
        raise PlanReviewValidationError("$.issues ROUTE_RECONSIDERATION requires issues")
    if status is ReviewResult.CONFIRM and result["confirmation"] is None:
        raise PlanReviewValidationError("$.confirmation CONFIRM requires confirmation")
    if status is ReviewResult.BLOCK and not result["blockers"]:
        raise PlanReviewValidationError("$.blockers BLOCK requires blockers")
    if status is ReviewResult.RETRIEVE_MORE and result["additional_acquisition_request"] is None:
        raise PlanReviewValidationError(
            "$.additional_acquisition_request RETRIEVE_MORE requires additional_acquisition_request"
        )
    if (
        status is not ReviewResult.RETRIEVE_MORE
        and result["additional_acquisition_request"] is not None
    ):
        raise PlanReviewValidationError(
            "$.additional_acquisition_request is only allowed for RETRIEVE_MORE"
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


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=PlanReviewValidationError)
_nullable_mapping = partial(_schema.nullable_mapping, error_cls=PlanReviewValidationError)
_require_allowed_keys = partial(_schema.require_allowed_keys, error_cls=PlanReviewValidationError)
_require_int = partial(_schema.require_int, error_cls=PlanReviewValidationError)
_require_string = partial(_schema.require_string, error_cls=PlanReviewValidationError)
_require_list = partial(_schema.require_list, error_cls=PlanReviewValidationError)
_require_string_list = partial(_schema.require_string_list, error_cls=PlanReviewValidationError)
_require_schema_version = partial(
    _schema.require_schema_version, error_cls=PlanReviewValidationError
)
_optional_string_list = partial(_schema.optional_string_list, error_cls=PlanReviewValidationError)
_optional_option_list = partial(_schema.optional_option_list, error_cls=PlanReviewValidationError)
_validated_string_refs = partial(_schema.validated_string_refs, error_cls=PlanReviewValidationError)
_provider_summary = _schema.provider_summary


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
