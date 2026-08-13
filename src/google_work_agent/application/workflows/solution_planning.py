"""Solution planning workflow node implementation."""

from __future__ import annotations

import copy
from functools import partial
from pathlib import Path
from typing import Final, Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import _schema_support as _schema
from google_work_agent.application.workflows.context_retrieval import ContextRetrievalResultV1
from google_work_agent.application.workflows.contracts import (
    GraphStateUpdateV1,
    PlanningResult,
    WorkflowPhase,
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
from google_work_agent.application.workflows.work_analysis import WorkAnalysisResultV1
from google_work_agent.domain import (
    EffectType,
    EvidencePolicyInput,
    PolicyViolationError,
    SignedToolRegistry,
    build_p0_tool_registry,
    validate_evidence_policy,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]
AnswerDraftStatusValue = Literal["ANSWER_ONLY", "NEEDS_CONFIRMATION", "BLOCKED"]
PlanDraftStatusValue = Literal["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]


class AnswerDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: AnswerDraftStatusValue
    answer: str
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    reason_codes: list[str]
    confirmation: dict[str, object] | None
    blockers: list[str]
    llm_provider_result: NotRequired[dict[str, object]]


class ActionDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    action_id: str
    position: int
    effect: ActionEffectValue
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_refs: list[str]
    resource_refs: list[str]
    target_resource_ref_id: str | None
    depends_on_action_ids: list[str]
    user_visible_reason: str


class ActionPlanDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: PlanDraftStatusValue
    plan_id: str
    summary: str
    objective: str
    actions: list[ActionDraftV1]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    confirmation: dict[str, object] | None
    llm_provider_result: NotRequired[dict[str, object]]


ANSWER_DRAFT_SCHEMA_VERSION: Final = 1
ACTION_PLAN_DRAFT_SCHEMA_VERSION: Final = 2
ACTION_DRAFT_SCHEMA_VERSION: Final = 2
_ACTION_DRAFT_ITEM_SCHEMA: Final = {
    "type": "object",
    "required": [
        "schema_version",
        "action_id",
        "position",
        "effect",
        "tool_name",
        "arguments",
        "expected",
        "evidence_refs",
        "resource_refs",
        "target_resource_ref_id",
        "depends_on_action_ids",
        "user_visible_reason",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "enum": [ACTION_DRAFT_SCHEMA_VERSION]},
        "action_id": {"type": "string", "minLength": 1},
        "position": {"type": "integer", "minimum": 1},
        "effect": {
            "type": "string",
            "enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"],
        },
        "tool_name": {"type": "string", "minLength": 1},
        "arguments": {"type": "object"},
        "expected": {"type": "object"},
        "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "resource_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "target_resource_ref_id": {"type": ["string", "null"]},
        "depends_on_action_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "user_visible_reason": {"type": "string", "minLength": 1},
    },
}
ANSWER_DRAFT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="answer-draft-v1",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "answer",
            "evidence_refs",
            "resource_refs",
            "reason_codes",
            "confirmation",
            "blockers",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "status": {
                "type": "string",
                "enum": ["ANSWER_ONLY", "NEEDS_CONFIRMATION", "BLOCKED"],
            },
            "answer": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            # Echoed context_bundle entries -- see _validated_resource_ref_objects
            # below, which only requires resource_handle and tolerates extra
            # fields, so additionalProperties stays permissive here.
            "resource_refs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["resource_handle"],
                    "properties": {"resource_handle": {"type": "string"}},
                },
            },
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "confirmation": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "string"}},
        },
    },
)
ACTION_PLAN_DRAFT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="action-plan-draft-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "plan_id",
            "summary",
            "objective",
            "actions",
            "evidence_refs",
            "resource_refs",
            "confirmation",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [ACTION_PLAN_DRAFT_SCHEMA_VERSION]},
            "status": {
                "type": "string",
                "enum": ["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
            },
            "plan_id": {"type": "string"},
            "summary": {"type": "string"},
            "objective": {"type": "string"},
            "actions": {"type": "array", "items": _ACTION_DRAFT_ITEM_SCHEMA},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            # Echoed context_bundle entries -- see _validated_resource_ref_objects
            # below, which only requires resource_handle and tolerates extra
            # fields, so additionalProperties stays permissive here.
            "resource_refs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["resource_handle"],
                    "properties": {"resource_handle": {"type": "string"}},
                },
            },
            "confirmation": {"type": ["object", "null"]},
        },
    },
)


def _action_plan_draft_output_schema_for_registry(
    tool_registry: SignedToolRegistry,
) -> OutputSchemaDefinition:
    """Invocation-scoped variant of ``ACTION_PLAN_DRAFT_OUTPUT_SCHEMA``.

    Constrains ``actions[].tool_name`` to the tool names actually present in
    ``tool_registry`` at call time, instead of a hardcoded P0 enum baked into
    the shared module-level schema constant -- which would silently break
    ``SolutionPlanningAgent``'s existing support for per-instance custom
    ``tool_registry`` injection (a different registry would then contain
    "unregistered" tool names the schema itself forbids). The base
    ``ACTION_PLAN_DRAFT_OUTPUT_SCHEMA`` constant is left untouched for
    callers that only need the generic (registry-agnostic) contract, e.g.
    ``controlled_post_retrieval.py``'s Gold evaluation dispatch and
    ``r84_gate_runner.py``'s static Gate dataset mapping.
    """

    tool_names = sorted(entry.tool_name for entry in tool_registry.list_entries())
    base_schema = dict(ACTION_PLAN_DRAFT_OUTPUT_SCHEMA.json_schema)
    json_schema: dict[str, object] = copy.deepcopy(base_schema)
    properties = cast("dict[str, object]", json_schema["properties"])
    actions_schema = cast("dict[str, object]", properties["actions"])
    action_item_schema = cast("dict[str, object]", actions_schema["items"])
    action_item_properties = cast("dict[str, object]", action_item_schema["properties"])
    action_item_properties["tool_name"] = {"type": "string", "enum": tool_names}
    return OutputSchemaDefinition(
        schema_version=ACTION_PLAN_DRAFT_OUTPUT_SCHEMA.schema_version,
        json_schema=json_schema,
    )


_ANSWER_RESULT_VALUES = {
    PlanningResult.ANSWER_ONLY.value,
    PlanningResult.NEEDS_CONFIRMATION.value,
    PlanningResult.BLOCKED.value,
}
_PLAN_RESULT_VALUES = {
    PlanningResult.PLAN_READY.value,
    PlanningResult.NEEDS_CONFIRMATION.value,
    PlanningResult.BLOCKED.value,
}
_ACTION_EFFECT_VALUES = {
    EffectType.READ.value,
    EffectType.CREATE.value,
    EffectType.UPDATE.value,
    EffectType.SEND.value,
    EffectType.DELETE.value,
}


class SolutionPlanningValidationError(ValueError):
    """Raised when solution planning structured output is invalid."""


class SolutionPlanningAgent:
    """Build or revise answer drafts and action-plan drafts without execution or approval."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        answer_only_prompt_ref: PromptReference | None = None,
        draft_plan_prompt_ref: PromptReference | None = None,
        revise_answer_prompt_ref: PromptReference | None = None,
        revise_plan_prompt_ref: PromptReference | None = None,
        tool_registry: SignedToolRegistry | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._answer_only_prompt_ref = (
            answer_only_prompt_ref
            or load_solution_planning_answer_only_prompt_reference(manifest_path)
        )
        self._draft_plan_prompt_ref = (
            draft_plan_prompt_ref
            or load_solution_planning_draft_plan_prompt_reference(manifest_path)
        )
        self._revise_answer_prompt_ref = (
            revise_answer_prompt_ref
            or load_solution_planning_revise_answer_prompt_reference(manifest_path)
        )
        self._revise_plan_prompt_ref = (
            revise_plan_prompt_ref
            or load_solution_planning_revise_plan_prompt_reference(manifest_path)
        )
        self._tool_registry = tool_registry or build_p0_tool_registry()

    @property
    def answer_only_prompt_ref(self) -> PromptReference:
        return self._answer_only_prompt_ref

    @property
    def draft_plan_prompt_ref(self) -> PromptReference:
        return self._draft_plan_prompt_ref

    @property
    def revise_answer_prompt_ref(self) -> PromptReference:
        return self._revise_answer_prompt_ref

    @property
    def revise_plan_prompt_ref(self) -> PromptReference:
        return self._revise_plan_prompt_ref

    def answer_only(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> AnswerDraftV1:
        llm_result = self.invoke_answer_only_llm(
            request_intent=request_intent,
            context_result=context_result,
            analysis_result=analysis_result,
            request=request,
        )
        return self.build_answer_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
        )

    def invoke_answer_only_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._answer_only_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "request_intent": request_intent,
                "context_status": context_result["status"],
                "context_bundle": context_result["context_bundle"],
                "evidence_drafts": context_result["evidence_drafts"],
                "analysis_result": analysis_result,
                "source_content_is_untrusted": True,
            },
            output_schema=ANSWER_DRAFT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.answer_only",
            ),
            semantic_validate=lambda candidate: validate_answer_draft_v1(
                candidate, analysis_result=analysis_result
            ),
        )

    def build_answer_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        analysis_result: WorkAnalysisResultV1,
    ) -> AnswerDraftV1:
        result = validate_answer_draft_v1(
            llm_result.structured_output,
            analysis_result=analysis_result,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def draft_plan(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> ActionPlanDraftV1:
        llm_result = self.invoke_draft_plan_llm(
            request_intent=request_intent,
            context_result=context_result,
            analysis_result=analysis_result,
            request=request,
        )
        return self.build_plan_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
        )

    def invoke_draft_plan_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._draft_plan_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "request_intent": request_intent,
                "context_status": context_result["status"],
                "context_bundle": context_result["context_bundle"],
                "evidence_drafts": context_result["evidence_drafts"],
                "analysis_result": analysis_result,
                "source_content_is_untrusted": True,
            },
            output_schema=_action_plan_draft_output_schema_for_registry(self._tool_registry),
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.draft_plan",
            ),
            semantic_validate=lambda candidate: validate_action_plan_draft_v1(
                candidate, analysis_result=analysis_result, tool_registry=self._tool_registry
            ),
        )

    def build_plan_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        analysis_result: WorkAnalysisResultV1,
    ) -> ActionPlanDraftV1:
        result = validate_action_plan_draft_v1(
            llm_result.structured_output,
            analysis_result=analysis_result,
            tool_registry=self._tool_registry,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def revise_answer(
        self,
        *,
        request_intent: RequestIntentV1,
        answer_draft: AnswerDraftV1,
        review_issues: list[dict[str, object]],
        review_summary: str | None,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> AnswerDraftV1:
        llm_result = self.invoke_revise_answer_llm(
            request_intent=request_intent,
            answer_draft=answer_draft,
            review_issues=review_issues,
            review_summary=review_summary,
            context_result=context_result,
            analysis_result=analysis_result,
            request=request,
        )
        return self.build_answer_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
        )

    def invoke_revise_answer_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        answer_draft: AnswerDraftV1,
        review_issues: list[dict[str, object]],
        review_summary: str | None,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._revise_answer_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "request_intent": request_intent,
                "answer_draft": answer_draft,
                "review_summary": review_summary,
                "review_issues": [dict(issue) for issue in review_issues],
                "context_status": context_result["status"],
                "context_bundle": context_result["context_bundle"],
                "evidence_drafts": context_result["evidence_drafts"],
                "analysis_result": analysis_result,
                "source_content_is_untrusted": True,
            },
            output_schema=ANSWER_DRAFT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.revise_answer",
            ),
        )

    def revise_plan(
        self,
        *,
        request_intent: RequestIntentV1,
        plan_draft: ActionPlanDraftV1,
        review_issues: list[dict[str, object]],
        review_summary: str | None,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> ActionPlanDraftV1:
        llm_result = self.invoke_revise_plan_llm(
            request_intent=request_intent,
            plan_draft=plan_draft,
            review_issues=review_issues,
            review_summary=review_summary,
            context_result=context_result,
            analysis_result=analysis_result,
            request=request,
        )
        return self.build_plan_output_from_llm_result(
            llm_result,
            analysis_result=analysis_result,
        )

    def invoke_revise_plan_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        plan_draft: ActionPlanDraftV1,
        review_issues: list[dict[str, object]],
        review_summary: str | None,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._revise_plan_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "request_intent": request_intent,
                "plan_draft": plan_draft,
                "review_summary": review_summary,
                "review_issues": [dict(issue) for issue in review_issues],
                "context_status": context_result["status"],
                "context_bundle": context_result["context_bundle"],
                "evidence_drafts": context_result["evidence_drafts"],
                "analysis_result": analysis_result,
                "source_content_is_untrusted": True,
            },
            output_schema=ACTION_PLAN_DRAFT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.revise_plan",
            ),
        )

    def build_answer_state_update(self, result: AnswerDraftV1) -> GraphStateUpdateV1:
        phase = (
            WorkflowPhase.PLAN_REVIEW
            if PlanningResult(result["status"]) is PlanningResult.ANSWER_ONLY
            else WorkflowPhase.SOLUTION_PLANNING
        )
        update: GraphStateUpdateV1 = {
            "workflow_phase": phase.value,
            "answer_draft": None,
            "plan_draft": None,
            "trace_context": {
                "planning_result": result["status"],
                "answer_evidence_count": len(result["evidence_refs"]),
                "answer_resource_count": len(result["resource_refs"]),
                "blocker_count": len(result["blockers"]),
            },
        }
        if PlanningResult(result["status"]) is PlanningResult.ANSWER_ONLY:
            update["answer_draft"] = result
        return update

    def build_plan_state_update(self, result: ActionPlanDraftV1) -> GraphStateUpdateV1:
        phase = (
            WorkflowPhase.PLAN_REVIEW
            if PlanningResult(result["status"]) is PlanningResult.PLAN_READY
            else WorkflowPhase.SOLUTION_PLANNING
        )
        update: GraphStateUpdateV1 = {
            "workflow_phase": phase.value,
            "answer_draft": None,
            "plan_draft": None,
            "trace_context": {
                "planning_result": result["status"],
                "action_count": len(result["actions"]),
                "plan_evidence_count": len(result["evidence_refs"]),
                "plan_resource_count": len(result["resource_refs"]),
            },
        }
        if PlanningResult(result["status"]) is PlanningResult.PLAN_READY:
            update["plan_draft"] = result
        return update

    def build_state_update(self, result: AnswerDraftV1 | ActionPlanDraftV1) -> GraphStateUpdateV1:
        if "answer" in result:
            return self.build_answer_state_update(cast(AnswerDraftV1, result))
        return self.build_plan_state_update(cast(ActionPlanDraftV1, result))


def validate_answer_draft_v1(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
) -> AnswerDraftV1:
    root = _require_mapping(value, "$")
    _require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "status",
            "answer",
            "evidence_refs",
            "resource_refs",
            "reason_codes",
            "confirmation",
            "blockers",
        },
        optional={"llm_provider_result"},
    )
    _require_schema_version(root, "$", ANSWER_DRAFT_SCHEMA_VERSION)
    refs = _reference_space(analysis_result)
    status = _require_string(root, "status", "$")
    if status not in _ANSWER_RESULT_VALUES:
        raise SolutionPlanningValidationError("$.status is invalid")
    result: AnswerDraftV1 = {
        "schema_version": ANSWER_DRAFT_SCHEMA_VERSION,
        "status": cast(AnswerDraftStatusValue, status),
        "answer": _require_string(root, "answer", "$"),
        "evidence_refs": _validated_evidence_refs(root["evidence_refs"], refs),
        "resource_refs": _validated_resource_ref_objects(root["resource_refs"], refs),
        "reason_codes": _require_string_list(root["reason_codes"], "$.reason_codes"),
        "confirmation": _nullable_mapping(root["confirmation"], "$.confirmation"),
        "blockers": _require_string_list(root["blockers"], "$.blockers"),
    }
    if "llm_provider_result" in root:
        result["llm_provider_result"] = _require_mapping(
            root["llm_provider_result"],
            "$.llm_provider_result",
        )
    _validate_answer_draft_invariant(result)
    return result


def validate_action_plan_draft_v1(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
    tool_registry: SignedToolRegistry | None = None,
) -> ActionPlanDraftV1:
    root = _require_mapping(value, "$")
    _require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "status",
            "plan_id",
            "summary",
            "objective",
            "actions",
            "evidence_refs",
            "resource_refs",
            "confirmation",
        },
        optional={"llm_provider_result"},
    )
    _require_schema_version(root, "$", ACTION_PLAN_DRAFT_SCHEMA_VERSION)
    registry = tool_registry or build_p0_tool_registry()
    refs = _reference_space(analysis_result)
    status = _require_string(root, "status", "$")
    if status not in _PLAN_RESULT_VALUES:
        raise SolutionPlanningValidationError("$.status is invalid")
    evidence_refs = _validated_evidence_refs(root["evidence_refs"], refs)
    resource_refs = _validated_resource_ref_objects(root["resource_refs"], refs)
    resource_handles = {
        str(ref["resource_handle"])
        for ref in resource_refs
        if isinstance(ref.get("resource_handle"), str)
    }
    actions = [
        _validate_action_draft(
            item,
            f"$.actions[{index}]",
            refs,
            registry=registry,
            plan_evidence_refs=set(evidence_refs),
            plan_resource_handles=resource_handles,
        )
        for index, item in enumerate(_require_list(root["actions"], "$.actions"))
    ]
    result: ActionPlanDraftV1 = {
        "schema_version": ACTION_PLAN_DRAFT_SCHEMA_VERSION,
        "status": cast(PlanDraftStatusValue, status),
        "plan_id": _require_string(root, "plan_id", "$"),
        "summary": _require_string(root, "summary", "$"),
        "objective": _require_string(root, "objective", "$"),
        "actions": _validate_action_collection(actions),
        "evidence_refs": evidence_refs,
        "resource_refs": resource_refs,
        "confirmation": _nullable_mapping(root["confirmation"], "$.confirmation"),
    }
    if "llm_provider_result" in root:
        result["llm_provider_result"] = _require_mapping(
            root["llm_provider_result"],
            "$.llm_provider_result",
        )
    _validate_action_plan_invariant(result)
    return result


def build_solution_planning_clarification_question(
    *,
    result: AnswerDraftV1 | ActionPlanDraftV1,
    request_intent: RequestIntentV1,
) -> ClarificationQuestionV1:
    confirmation = _require_mapping(result["confirmation"], "$.confirmation")
    origin_target = "planning.answer_only" if "answer" in result else "planning.draft_plan"
    return build_clarification_question_v1(
        origin_target=origin_target,
        question=_require_string(confirmation, "question", "$.confirmation"),
        reason_code=_require_string(confirmation, "reason_code", "$.confirmation"),
        known_context_summary=request_intent["goal"]["user_visible_objective"]
        or request_intent["goal"]["summary"],
        affected_field_paths=_optional_string_list(confirmation.get("affected_field_paths")),
        options=_optional_option_list(confirmation.get("options")),
    )


def load_solution_planning_answer_only_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "planning.answer_only",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_solution_planning_draft_plan_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "planning.draft_plan",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_solution_planning_revise_answer_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "planning.revise_answer",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_solution_planning_revise_plan_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "planning.revise_plan",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def _validate_action_draft(
    value: object,
    path: str,
    refs: _ReferenceSpace,
    *,
    registry: SignedToolRegistry,
    plan_evidence_refs: set[str],
    plan_resource_handles: set[str],
) -> ActionDraftV1:
    action = _require_mapping(value, path)
    _require_allowed_keys(
        action,
        path,
        required={
            "schema_version",
            "action_id",
            "position",
            "effect",
            "tool_name",
            "arguments",
            "expected",
            "evidence_refs",
            "resource_refs",
            "target_resource_ref_id",
            "depends_on_action_ids",
            "user_visible_reason",
        },
        optional=set(),
    )
    _require_schema_version(action, path, ACTION_DRAFT_SCHEMA_VERSION)
    tool_name = _require_string(action, "tool_name", path)
    entry = registry.get(tool_name)
    if entry is None:
        raise SolutionPlanningValidationError(f"{path}.tool_name tool not registered: {tool_name}")
    effect = _require_string(action, "effect", path)
    if effect not in _ACTION_EFFECT_VALUES:
        raise SolutionPlanningValidationError(f"{path}.effect is invalid")
    if effect != entry.effect_type.value:
        raise SolutionPlanningValidationError(f"{path}.effect does not match tool policy")
    evidence_refs = _validated_string_refs(
        action["evidence_refs"],
        refs["evidence_ids"],
        f"{path}.evidence_refs",
        "evidence",
    )
    resource_refs = _validated_string_refs(
        action["resource_refs"],
        refs["resource_handles"],
        f"{path}.resource_refs",
        "resource",
    )
    for evidence_ref in evidence_refs:
        if evidence_ref not in plan_evidence_refs:
            raise SolutionPlanningValidationError(
                f"{path}.evidence_refs must be covered by plan evidence_refs"
            )
    for resource_ref in resource_refs:
        if resource_ref not in plan_resource_handles:
            raise SolutionPlanningValidationError(
                f"{path}.resource_refs must be covered by plan resource_refs"
            )
    target_resource_ref_id = _optional_string(action.get("target_resource_ref_id"))
    if (
        target_resource_ref_id is not None
        and target_resource_ref_id not in refs["resource_handles"]
    ):
        raise SolutionPlanningValidationError(
            f"target resource reference does not exist: {target_resource_ref_id}"
        )
    depends_on_action_ids = _require_string_list(
        action["depends_on_action_ids"],
        f"{path}.depends_on_action_ids",
    )
    if len(depends_on_action_ids) != len(set(depends_on_action_ids)):
        raise SolutionPlanningValidationError(f"{path}.depends_on_action_ids has duplicates")
    try:
        validate_evidence_policy(
            EvidencePolicyInput(
                evidence_count=len(evidence_refs),
                requires_existing_resource=entry.effect_type
                in {EffectType.UPDATE, EffectType.DELETE},
                has_user_selected_resource=target_resource_ref_id is not None,
                has_explicit_resource_relation=target_resource_ref_id is not None,
            )
        )
    except PolicyViolationError as error:
        raise SolutionPlanningValidationError(str(error)) from error
    return {
        "schema_version": ACTION_DRAFT_SCHEMA_VERSION,
        "action_id": _require_string(action, "action_id", path),
        "position": _require_int(action, "position", path),
        "effect": cast(ActionEffectValue, effect),
        "tool_name": tool_name,
        "arguments": _require_mapping(action["arguments"], f"{path}.arguments"),
        "expected": _require_mapping(action["expected"], f"{path}.expected"),
        "evidence_refs": evidence_refs,
        "resource_refs": resource_refs,
        "target_resource_ref_id": target_resource_ref_id,
        "depends_on_action_ids": depends_on_action_ids,
        "user_visible_reason": _require_string(action, "user_visible_reason", path),
    }


def _validate_action_collection(actions: list[ActionDraftV1]) -> list[ActionDraftV1]:
    if not actions:
        return actions
    action_ids = [action["action_id"] for action in actions]
    if len(action_ids) != len(set(action_ids)):
        raise SolutionPlanningValidationError("duplicate action_id in plan draft")
    positions = [action["position"] for action in actions]
    if len(positions) != len(set(positions)):
        raise SolutionPlanningValidationError("duplicate action position in plan draft")
    adjacency: dict[str, list[str]] = {}
    action_id_set = set(action_ids)
    for action in actions:
        if action["action_id"] in action["depends_on_action_ids"]:
            raise SolutionPlanningValidationError("action cannot depend on itself")
        for dependency in action["depends_on_action_ids"]:
            if dependency not in action_id_set:
                raise SolutionPlanningValidationError(f"action dependency not found: {dependency}")
        adjacency[action["action_id"]] = list(action["depends_on_action_ids"])
    _validate_no_dependency_cycle(adjacency)
    return sorted(actions, key=lambda item: item["position"])


def _validate_no_dependency_cycle(adjacency: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise SolutionPlanningValidationError("action dependency cycle detected")
        visiting.add(node)
        for dependency in adjacency[node]:
            _visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        _visit(node)


def _validate_answer_draft_invariant(result: AnswerDraftV1) -> None:
    status = PlanningResult(result["status"])
    if status is PlanningResult.ANSWER_ONLY:
        if result["confirmation"] is not None:
            raise SolutionPlanningValidationError(
                "$.confirmation ANSWER_ONLY must not include confirmation"
            )
        if result["blockers"]:
            raise SolutionPlanningValidationError(
                "$.blockers ANSWER_ONLY must not include blockers"
            )
    if status is PlanningResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise SolutionPlanningValidationError(
            "$.confirmation NEEDS_CONFIRMATION requires confirmation"
        )
    if status is PlanningResult.BLOCKED and not result["blockers"]:
        raise SolutionPlanningValidationError("$.blockers BLOCKED requires blockers")


def _validate_action_plan_invariant(result: ActionPlanDraftV1) -> None:
    status = PlanningResult(result["status"])
    if status is PlanningResult.PLAN_READY:
        if not result["actions"]:
            raise SolutionPlanningValidationError(
                "$.actions PLAN_READY requires at least one action"
            )
        if result["confirmation"] is not None:
            raise SolutionPlanningValidationError(
                "$.confirmation PLAN_READY must not include confirmation"
            )
    if status is PlanningResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise SolutionPlanningValidationError(
            "$.confirmation NEEDS_CONFIRMATION requires confirmation"
        )
    if status is not PlanningResult.PLAN_READY and result["actions"]:
        raise SolutionPlanningValidationError(
            "$.actions non-PLAN_READY planning results must not include action drafts"
        )


class _ReferenceSpace(TypedDict):
    evidence_ids: set[str]
    resource_handles: set[str]


def _reference_space(analysis_result: WorkAnalysisResultV1) -> _ReferenceSpace:
    return {
        "evidence_ids": set(analysis_result["evidence_refs"]),
        "resource_handles": {
            str(ref["resource_handle"])
            for ref in analysis_result["resource_refs"]
            if isinstance(ref.get("resource_handle"), str)
        },
    }


def _validated_evidence_refs(value: object, refs: _ReferenceSpace) -> list[str]:
    return _validated_string_refs(value, refs["evidence_ids"], "$.evidence_refs", "evidence")


def _validated_resource_ref_objects(
    value: object,
    refs: _ReferenceSpace,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, item in enumerate(_require_list(value, "$.resource_refs")):
        ref = _require_mapping(item, f"$.resource_refs[{index}]")
        handle = _require_string(ref, "resource_handle", f"$.resource_refs[{index}]")
        if handle not in refs["resource_handles"]:
            raise SolutionPlanningValidationError(f"resource reference does not exist: {handle}")
        result.append(ref)
    return result


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=SolutionPlanningValidationError)
_nullable_mapping = partial(_schema.nullable_mapping, error_cls=SolutionPlanningValidationError)
_require_allowed_keys = partial(
    _schema.require_allowed_keys, error_cls=SolutionPlanningValidationError
)
_require_int = partial(_schema.require_int, error_cls=SolutionPlanningValidationError)
_require_string = partial(_schema.require_string, error_cls=SolutionPlanningValidationError)
_require_list = partial(_schema.require_list, error_cls=SolutionPlanningValidationError)
_require_string_list = partial(
    _schema.require_string_list, error_cls=SolutionPlanningValidationError
)
_require_schema_version = partial(
    _schema.require_schema_version, error_cls=SolutionPlanningValidationError
)
_optional_string_list = partial(
    _schema.optional_string_list, error_cls=SolutionPlanningValidationError
)
_optional_option_list = partial(
    _schema.optional_option_list, error_cls=SolutionPlanningValidationError
)
_validated_string_refs = partial(
    _schema.validated_string_refs, error_cls=SolutionPlanningValidationError
)
_provider_summary = _schema.provider_summary


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SolutionPlanningValidationError("optional string field must be string")
    return value


__all__ = [
    "ACTION_DRAFT_SCHEMA_VERSION",
    "ACTION_PLAN_DRAFT_OUTPUT_SCHEMA",
    "ACTION_PLAN_DRAFT_SCHEMA_VERSION",
    "ANSWER_DRAFT_OUTPUT_SCHEMA",
    "ANSWER_DRAFT_SCHEMA_VERSION",
    "ActionDraftV1",
    "ActionPlanDraftV1",
    "AnswerDraftV1",
    "build_solution_planning_clarification_question",
    "SolutionPlanningAgent",
    "SolutionPlanningValidationError",
    "load_solution_planning_answer_only_prompt_reference",
    "load_solution_planning_draft_plan_prompt_reference",
    "load_solution_planning_revise_answer_prompt_reference",
    "load_solution_planning_revise_plan_prompt_reference",
    "validate_action_plan_draft_v1",
    "validate_answer_draft_v1",
]
