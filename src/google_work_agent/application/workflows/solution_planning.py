"""Solution planning workflow node implementation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.context_retrieval import ContextRetrievalResultV1
from google_work_agent.application.workflows.contracts import PlanningResult, WorkflowPhase
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
ActionEffectValue = Literal["READ", "CREATE", "UPDATE"]


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
    schema_version: Required[Literal[1]]
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
    schema_version: Required[Literal[1]]
    status: PlanDraftStatusValue
    plan_id: str
    summary: str
    objective: str
    actions: list[ActionDraftV1]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    confirmation: dict[str, object] | None
    llm_provider_result: NotRequired[dict[str, object]]


ANSWER_DRAFT_SCHEMA_VERSION = 1
ACTION_PLAN_DRAFT_SCHEMA_VERSION = 1
ACTION_DRAFT_SCHEMA_VERSION = 1
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
            "resource_refs": {"type": "array", "items": {"type": "object"}},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "confirmation": {},
            "blockers": {"type": "array", "items": {"type": "string"}},
        },
    },
)
ACTION_PLAN_DRAFT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="action-plan-draft-v1",
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
            "schema_version": {"type": "integer", "enum": [1]},
            "status": {
                "type": "string",
                "enum": ["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
            },
            "plan_id": {"type": "string"},
            "summary": {"type": "string"},
            "objective": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "object"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "resource_refs": {"type": "array", "items": {"type": "object"}},
            "confirmation": {},
        },
    },
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
_ACTION_EFFECT_VALUES = {EffectType.READ.value, EffectType.CREATE.value, EffectType.UPDATE.value}


class SolutionPlanningValidationError(ValueError):
    """Raised when solution planning structured output is invalid."""


class SolutionPlanningAgent:
    """Build or revise answer drafts and action-plan drafts without execution or approval."""

    def __init__(
        self,
        *,
        llm_runtime: LLMRuntimeService,
        answer_only_prompt_ref: PromptReference | None = None,
        draft_plan_prompt_ref: PromptReference | None = None,
        revise_answer_prompt_ref: PromptReference | None = None,
        revise_plan_prompt_ref: PromptReference | None = None,
        tool_registry: SignedToolRegistry | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._answer_only_prompt_ref = (
            answer_only_prompt_ref or load_solution_planning_answer_only_prompt_reference()
        )
        self._draft_plan_prompt_ref = (
            draft_plan_prompt_ref or load_solution_planning_draft_plan_prompt_reference()
        )
        self._revise_answer_prompt_ref = (
            revise_answer_prompt_ref or load_solution_planning_revise_answer_prompt_reference()
        )
        self._revise_plan_prompt_ref = (
            revise_plan_prompt_ref or load_solution_planning_revise_plan_prompt_reference()
        )
        self._tool_registry = tool_registry or build_p0_tool_registry()

    def answer_only(
        self,
        *,
        request_intent: RequestIntentV1,
        context_result: ContextRetrievalResultV1,
        analysis_result: WorkAnalysisResultV1,
        request: WorkflowStartRequest,
    ) -> AnswerDraftV1:
        llm_result = self._llm_runtime.invoke_structured(
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
        )
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
        llm_result = self._llm_runtime.invoke_structured(
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
            output_schema=ACTION_PLAN_DRAFT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.draft_plan",
            ),
        )
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
        llm_result = self._llm_runtime.invoke_structured(
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
        result = validate_answer_draft_v1(
            llm_result.structured_output,
            analysis_result=analysis_result,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

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
        llm_result = self._llm_runtime.invoke_structured(
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
        result = validate_action_plan_draft_v1(
            llm_result.structured_output,
            analysis_result=analysis_result,
            tool_registry=self._tool_registry,
        )
        result["llm_provider_result"] = _provider_summary(llm_result)
        return result

    def build_answer_state_update(self, result: AnswerDraftV1) -> JsonObject:
        phase = (
            WorkflowPhase.PLAN_REVIEW
            if PlanningResult(result["status"]) is PlanningResult.ANSWER_ONLY
            else WorkflowPhase.SOLUTION_PLANNING
        )
        update: JsonObject = {
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

    def build_plan_state_update(self, result: ActionPlanDraftV1) -> JsonObject:
        phase = (
            WorkflowPhase.PLAN_REVIEW
            if PlanningResult(result["status"]) is PlanningResult.PLAN_READY
            else WorkflowPhase.SOLUTION_PLANNING
        )
        update: JsonObject = {
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

    def build_state_update(self, result: AnswerDraftV1 | ActionPlanDraftV1) -> JsonObject:
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
        "schema_version": 1,
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
        "schema_version": 1,
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
    return _load_prompt_reference(
        "planning.answer_only",
        manifest_path or _default_prompt_manifest_path(),
    )


def load_solution_planning_draft_plan_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_prompt_reference(
        "planning.draft_plan",
        manifest_path or _default_prompt_manifest_path(),
    )


def load_solution_planning_revise_answer_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_prompt_reference(
        "planning.revise_answer",
        manifest_path or _default_prompt_manifest_path(),
    )


def load_solution_planning_revise_plan_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_prompt_reference(
        "planning.revise_plan",
        manifest_path or _default_prompt_manifest_path(),
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
        raise SolutionPlanningValidationError(f"tool not registered: {tool_name}")
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
                requires_existing_resource=entry.effect_type is EffectType.UPDATE,
                has_user_selected_resource=target_resource_ref_id is not None,
                has_explicit_resource_relation=target_resource_ref_id is not None,
            )
        )
    except PolicyViolationError as error:
        raise SolutionPlanningValidationError(str(error)) from error
    return {
        "schema_version": 1,
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
            raise SolutionPlanningValidationError("ANSWER_ONLY must not include confirmation")
        if result["blockers"]:
            raise SolutionPlanningValidationError("ANSWER_ONLY must not include blockers")
    if status is PlanningResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise SolutionPlanningValidationError("NEEDS_CONFIRMATION requires confirmation")
    if status is PlanningResult.BLOCKED and not result["blockers"]:
        raise SolutionPlanningValidationError("BLOCKED requires blockers")


def _validate_action_plan_invariant(result: ActionPlanDraftV1) -> None:
    status = PlanningResult(result["status"])
    if status is PlanningResult.PLAN_READY:
        if not result["actions"]:
            raise SolutionPlanningValidationError("PLAN_READY requires at least one action")
        if result["confirmation"] is not None:
            raise SolutionPlanningValidationError("PLAN_READY must not include confirmation")
    if status is PlanningResult.NEEDS_CONFIRMATION and result["confirmation"] is None:
        raise SolutionPlanningValidationError("NEEDS_CONFIRMATION requires confirmation")
    if status is not PlanningResult.PLAN_READY and result["actions"]:
        raise SolutionPlanningValidationError(
            "non-PLAN_READY planning results must not include action drafts"
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


def _validated_string_refs(
    value: object,
    allowed: set[str],
    path: str,
    label: str,
) -> list[str]:
    refs = _require_string_list(value, path)
    for item in refs:
        if item not in allowed:
            raise SolutionPlanningValidationError(f"{label} reference does not exist: {item}")
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


def _load_prompt_reference(prompt_id: str, manifest_path: Path) -> PromptReference:
    manifest = _load_prompt_manifest(manifest_path)
    for item in manifest:
        if item.get("prompt_id") == prompt_id:
            return PromptReference(
                prompt_bundle_version=_required_manifest_string(item, "prompt_bundle_version"),
                prompt_id=_required_manifest_string(item, "prompt_id"),
                prompt_version=_required_manifest_string(item, "prompt_version"),
                content_hash=_required_manifest_string(item, "content_hash"),
                agent_role=_required_manifest_string(item, "agent_role"),
                subgraph_name=_required_manifest_string(item, "subgraph_name"),
                node_name=_required_manifest_string(item, "node_name"),
                node_state=_required_manifest_string(item, "node_state"),
                purpose=_required_manifest_string(item, "purpose"),
                input_schema_version=_required_manifest_string(item, "input_schema_version"),
                output_schema_version=_required_manifest_string(item, "output_schema_version"),
            )
    raise LookupError(f"{prompt_id} prompt is missing from manifest")


def _require_schema_version(value: dict[str, object], path: str, expected: int) -> None:
    schema_version = _require_int(value, "schema_version", path)
    if schema_version != expected:
        raise SolutionPlanningValidationError(f"{path}.schema_version must be {expected}")


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SolutionPlanningValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SolutionPlanningValidationError(f"{path} keys must be strings")
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
        raise SolutionPlanningValidationError(
            f"{path} is missing required fields: {sorted(missing)}"
        )
    if extra:
        raise SolutionPlanningValidationError(f"{path} has unsupported fields: {sorted(extra)}")


def _require_int(value: dict[str, object], field: str, path: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise SolutionPlanningValidationError(f"{path}.{field} must be integer")
    return item


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise SolutionPlanningValidationError(f"{path}.{field} must be string")
    return item


def _require_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise SolutionPlanningValidationError(f"{path} must be an array")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    items = _require_list(value, path)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise SolutionPlanningValidationError(f"{path}[{index}] must be string")
    return cast(list[str], items)


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.list")
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise SolutionPlanningValidationError(
                f"clarification list entry must be string: {index}"
            )
        result.append(item)
    return result


def _optional_option_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    items = _require_list(value, "$.clarification.options")
    return [_require_mapping(item, "$.clarification.options[]") for item in items]


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SolutionPlanningValidationError("optional string field must be string")
    return value


@lru_cache(maxsize=1)
def _load_prompt_manifest(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = payload.get("prompt_manifest") if isinstance(payload, dict) else None
    if not isinstance(manifest, list):
        raise ValueError("prompt manifest must contain prompt_manifest list")
    return [_require_mapping(item, "$.prompt_manifest[]") for item in manifest]


def _required_manifest_string(item: dict[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"prompt manifest field is required: {field}")
    if value == "TBD":
        raise ValueError(f"prompt manifest field is not runtime-active: {field}")
    return value


def _default_prompt_manifest_path() -> Path:
    return Path(__file__).resolve().parents[4] / "prompts" / "agent" / "manifest.yaml"


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
