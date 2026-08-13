"""Request-understanding workflow node implementation."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final, Literal, NotRequired, Required, TypedDict, cast

import google_work_agent.application.workflows._schema_support as _schema
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.contracts import (
    CONFIRMATION_ORIGIN_TARGETS,
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    RequestUnderstandingResult,
    UserInterruptV1,
    WorkflowPhase,
    validate_confirmation_origin_target,
    validate_confirmation_response_v1,
    validate_user_interrupt_v1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]


class ClarificationOptionV1(TypedDict):
    option_id: str
    label: str


class RequestIntentGoalV1(TypedDict):
    summary: str
    user_visible_objective: str


class RequestIntentTopicConstraintV1(TypedDict):
    text: str
    source_text: str


class RequestIntentPeopleConstraintV1(TypedDict):
    mention: str
    role_hint: str | None
    source_text: str


class RequestIntentTimeConstraintV1(TypedDict):
    mention: str
    granularity_hint: Literal["DATE", "DATETIME", "RANGE", "RELATIVE", "UNKNOWN"]
    source_text: str


class RequestIntentSourceConstraintV1(TypedDict):
    source: Literal["GMAIL", "TASKS", "CALENDAR", "UNKNOWN"]
    mention: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class RequestIntentStatusConstraintV1(TypedDict):
    mention: str
    source_text: str


class RequestIntentSemanticConstraintsV1(TypedDict):
    topics: list[RequestIntentTopicConstraintV1]
    people: list[RequestIntentPeopleConstraintV1]
    time: list[RequestIntentTimeConstraintV1]
    sources: list[RequestIntentSourceConstraintV1]
    status_or_state: list[RequestIntentStatusConstraintV1]
    negative_constraints: list[str]
    policy_or_safety_constraints: list[str]


class RequestIntentAmbiguityItemV1(TypedDict):
    field_path: str
    reason_code: str
    user_question: str


class RequestIntentAmbiguityV1(TypedDict):
    is_ambiguous: bool
    items: list[RequestIntentAmbiguityItemV1]


class RequestIntentUnsupportedScopeV1(TypedDict):
    is_unsupported: bool
    reason_code: str | None
    explanation: str | None


RequestIntentResponseDispositionValue = Literal["ANSWER_ONLY", "ACTION_REQUIRED"]
"""Deterministic planning-mode signal produced by request_understanding.classify.

Selects whether the Planning stage calls ``planning.answer_only`` or
``planning.draft_plan`` (docs/06-agent-workflow.md Node Registry). Optional
(``NotRequired``) rather than added to ``REQUEST_INTENT_SCHEMA_VERSION``'s
required set: profiles other than SIX_ROLE_BASELINE (SINGLE_BASELINE's
``profile.single.reason_plan.initial``, THREE_STAGE's
``profile.three.stage2.initial``) already decide ANSWER_ONLY vs PLAN_READY
inside their own fused planning output and never consult this field, so
their embedded ``RequestIntentV1`` payloads are not required to carry it.
"""


class RequestIntentV1(TypedDict):
    schema_version: Required[Literal[2]]
    goal: RequestIntentGoalV1
    completion_criteria: list[str]
    semantic_constraints: RequestIntentSemanticConstraintsV1
    ambiguity: RequestIntentAmbiguityV1
    unsupported_scope: RequestIntentUnsupportedScopeV1
    response_disposition: NotRequired[RequestIntentResponseDispositionValue]


class ClarificationQuestionV1(TypedDict):
    schema_version: Required[Literal[1]]
    origin_target: str
    question: str
    affected_field_paths: list[str]
    reason_code: str
    known_context_summary: str
    options: list[ClarificationOptionV1]


class RequestUnderstandingFailureV1(TypedDict):
    schema_version: Required[Literal[1]]
    reason_code: str
    user_safe_message: str
    diagnostic: str


class RequestUnderstandingOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["COMPLETE", "NEEDS_CONFIRMATION", "INVALID"]
    request_intent: RequestIntentV1 | None
    clarification: ClarificationQuestionV1 | None
    failure: RequestUnderstandingFailureV1 | None
    validator_codes: list[str]
    llm_provider_result: NotRequired[dict[str, object]]


REQUEST_INTENT_SCHEMA_VERSION: Final = 2
CLARIFICATION_QUESTION_SCHEMA_VERSION: Final = 1
REQUEST_UNDERSTANDING_OUTPUT_SCHEMA_VERSION: Final = 1
REQUEST_INTENT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-intent-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "goal",
            "completion_criteria",
            "semantic_constraints",
            "ambiguity",
            "unsupported_scope",
            "response_disposition",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [REQUEST_INTENT_SCHEMA_VERSION]},
            "goal": {
                "type": "object",
                "required": ["summary", "user_visible_objective"],
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "user_visible_objective": {"type": "string"},
                },
            },
            "completion_criteria": {"type": "array", "items": {"type": "string"}},
            "semantic_constraints": {
                "type": "object",
                "required": [
                    "topics",
                    "people",
                    "time",
                    "sources",
                    "status_or_state",
                    "negative_constraints",
                    "policy_or_safety_constraints",
                ],
                "additionalProperties": False,
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "source_text"],
                            "additionalProperties": False,
                            "properties": {
                                "text": {"type": "string"},
                                "source_text": {"type": "string"},
                            },
                        },
                    },
                    "people": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["mention", "role_hint", "source_text"],
                            "additionalProperties": False,
                            "properties": {
                                "mention": {"type": "string"},
                                "role_hint": {"type": ["string", "null"]},
                                "source_text": {"type": "string"},
                            },
                        },
                    },
                    "time": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["mention", "granularity_hint", "source_text"],
                            "additionalProperties": False,
                            "properties": {
                                "mention": {"type": "string"},
                                "granularity_hint": {
                                    "type": "string",
                                    "enum": ["DATE", "DATETIME", "RANGE", "RELATIVE", "UNKNOWN"],
                                },
                                "source_text": {"type": "string"},
                            },
                        },
                    },
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["source", "mention", "confidence"],
                            "additionalProperties": False,
                            "properties": {
                                "source": {
                                    "type": "string",
                                    "enum": ["GMAIL", "TASKS", "CALENDAR", "UNKNOWN"],
                                },
                                "mention": {"type": "string"},
                                "confidence": {
                                    "type": "string",
                                    "enum": ["HIGH", "MEDIUM", "LOW"],
                                },
                            },
                        },
                    },
                    "status_or_state": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["mention", "source_text"],
                            "additionalProperties": False,
                            "properties": {
                                "mention": {"type": "string"},
                                "source_text": {"type": "string"},
                            },
                        },
                    },
                    "negative_constraints": {"type": "array", "items": {"type": "string"}},
                    "policy_or_safety_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "ambiguity": {
                "type": "object",
                "required": ["is_ambiguous", "items"],
                "additionalProperties": False,
                "properties": {
                    "is_ambiguous": {"type": "boolean"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["field_path", "reason_code", "user_question"],
                            "additionalProperties": False,
                            "properties": {
                                "field_path": {"type": "string"},
                                "reason_code": {"type": "string"},
                                "user_question": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "unsupported_scope": {
                "type": "object",
                "required": ["is_unsupported", "reason_code", "explanation"],
                "additionalProperties": False,
                "properties": {
                    "is_unsupported": {"type": "boolean"},
                    "reason_code": {"type": ["string", "null"]},
                    "explanation": {"type": ["string", "null"]},
                },
            },
            "response_disposition": {
                "type": "string",
                "enum": ["ANSWER_ONLY", "ACTION_REQUIRED"],
            },
        },
    },
)
CLARIFICATION_QUESTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="clarification-question-v1",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "origin_target",
            "question",
            "affected_field_paths",
            "reason_code",
            "known_context_summary",
            "options",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "origin_target": {"type": "string", "enum": sorted(CONFIRMATION_ORIGIN_TARGETS)},
            "question": {"type": "string"},
            "affected_field_paths": {"type": "array", "items": {"type": "string"}},
            "reason_code": {"type": "string"},
            "known_context_summary": {"type": "string"},
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["option_id", "label"],
                    "additionalProperties": False,
                    "properties": {
                        "option_id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                },
            },
        },
    },
)

_TIME_GRANULARITY_VALUES = {"DATE", "DATETIME", "RANGE", "RELATIVE", "UNKNOWN"}
_SOURCE_VALUES = {"GMAIL", "TASKS", "CALENDAR", "UNKNOWN"}
_CONFIDENCE_VALUES = {"HIGH", "MEDIUM", "LOW"}


class RequestUnderstandingValidationError(ValueError):
    """Raised when a structured RequestIntentV1 is not semantically usable."""


class RequestUnderstandingAgent:
    """Classify a workflow start request into the RequestIntentV1 handoff."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference | None = None,
        clarify_prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref or load_request_understanding_classify_prompt_reference(
            manifest_path
        )
        self._clarify_prompt_ref = (
            clarify_prompt_ref or load_request_understanding_clarify_prompt_reference(manifest_path)
        )

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    def __call__(self, request: WorkflowStartRequest) -> RequestUnderstandingOutputV1:
        return self.classify(request)

    def classify(self, request: WorkflowStartRequest) -> RequestUnderstandingOutputV1:
        llm_result = self.invoke_classify_llm(request)
        return self.build_output_from_llm_result(llm_result)

    def invoke_classify_llm(self, request: WorkflowStartRequest) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=_prompt_input_from_request(request),
            output_schema=REQUEST_INTENT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:request_understanding.classify",
            ),
            semantic_validate=validate_request_intent_v1,
        )

    def build_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
    ) -> RequestUnderstandingOutputV1:
        intent = validate_request_intent_v1(llm_result.structured_output)
        return _classify_valid_intent(intent=intent, llm_result=llm_result)

    def clarify(
        self,
        clarification_source: ClarificationQuestionV1,
        *,
        request: WorkflowStartRequest,
    ) -> ClarificationQuestionV1:
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._clarify_prompt_ref,
            prompt_input={
                "request_text": request.request_text,
                "clarification_source": clarification_source,
            },
            output_schema=CLARIFICATION_QUESTION_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:request_understanding.clarify",
            ),
        )
        return validate_clarification_question_v1(llm_result.structured_output)

    def build_state_update(
        self,
        output: RequestUnderstandingOutputV1,
        *,
        request: WorkflowStartRequest,
    ) -> GraphStateUpdateV1:
        phase = _phase_for_result(RequestUnderstandingResult(output["result"]))
        return {
            "request_intent": output["request_intent"],
            "workflow_phase": phase.value,
            "prompt_context": {
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            "trace_context": {
                "request_understanding_result": output["result"],
                "validator_codes": list(output["validator_codes"]),
            },
        }


_RESPONSE_DISPOSITION_VALUES = {"ANSWER_ONLY", "ACTION_REQUIRED"}


def validate_request_intent_v1(value: object) -> RequestIntentV1:
    root = _require_mapping(value, "$")
    _require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "goal",
            "completion_criteria",
            "semantic_constraints",
            "ambiguity",
            "unsupported_scope",
        },
        optional={"response_disposition"},
    )
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != REQUEST_INTENT_SCHEMA_VERSION:
        raise RequestUnderstandingValidationError(
            f"$.schema_version must be {REQUEST_INTENT_SCHEMA_VERSION}"
        )
    goal = _validate_goal(root["goal"])
    completion_criteria = _require_string_list(root["completion_criteria"], "$.completion_criteria")
    semantic_constraints = _validate_semantic_constraints(root["semantic_constraints"])
    ambiguity = _validate_ambiguity(root["ambiguity"])
    unsupported_scope = _validate_unsupported_scope(root["unsupported_scope"])
    result = RequestIntentV1(
        schema_version=REQUEST_INTENT_SCHEMA_VERSION,
        goal=goal,
        completion_criteria=completion_criteria,
        semantic_constraints=semantic_constraints,
        ambiguity=ambiguity,
        unsupported_scope=unsupported_scope,
    )
    if "response_disposition" in root:
        response_disposition = _require_string(root, "response_disposition", "$")
        if response_disposition not in _RESPONSE_DISPOSITION_VALUES:
            raise RequestUnderstandingValidationError("$.response_disposition is invalid")
        result["response_disposition"] = cast(
            RequestIntentResponseDispositionValue, response_disposition
        )
    return result


def validate_clarification_question_v1(value: object) -> ClarificationQuestionV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "origin_target",
            "question",
            "affected_field_paths",
            "reason_code",
            "known_context_summary",
            "options",
        },
    )
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != CLARIFICATION_QUESTION_SCHEMA_VERSION:
        raise RequestUnderstandingValidationError(
            f"$.schema_version must be {CLARIFICATION_QUESTION_SCHEMA_VERSION}"
        )
    option_ids: set[str] = set()
    options: list[ClarificationOptionV1] = []
    for index, item in enumerate(_require_list(root["options"], "$.options")):
        option = _require_mapping(item, f"$.options[{index}]")
        _require_exact_keys(option, f"$.options[{index}]", {"option_id", "label"})
        option_id = _require_string(option, "option_id", f"$.options[{index}]")
        if not option_id.strip():
            raise RequestUnderstandingValidationError(
                f"$.options[{index}].option_id must not be empty"
            )
        if option_id in option_ids:
            raise RequestUnderstandingValidationError(
                f"duplicate clarification option_id: {option_id}"
            )
        option_ids.add(option_id)
        options.append(
            {
                "option_id": option_id,
                "label": _require_string(option, "label", f"$.options[{index}]"),
            }
        )
    return {
        "schema_version": 1,
        "origin_target": validate_confirmation_origin_target(root["origin_target"]),
        "question": _require_string(root, "question", "$"),
        "affected_field_paths": _require_string_list(
            root["affected_field_paths"],
            "$.affected_field_paths",
        ),
        "reason_code": _require_string(root, "reason_code", "$"),
        "known_context_summary": _require_string(root, "known_context_summary", "$"),
        "options": options,
    }


def build_clarification_question_v1(
    *,
    origin_target: str,
    question: str,
    reason_code: str,
    known_context_summary: str,
    affected_field_paths: list[str] | None = None,
    options: list[dict[str, object]] | None = None,
) -> ClarificationQuestionV1:
    return validate_clarification_question_v1(
        {
            "schema_version": 1,
            "origin_target": origin_target,
            "question": question,
            "affected_field_paths": list(affected_field_paths or []),
            "reason_code": reason_code,
            "known_context_summary": known_context_summary,
            "options": list(options or []),
        }
    )


def build_user_interrupt_v1(
    clarification_question: ClarificationQuestionV1,
) -> UserInterruptV1:
    question = validate_clarification_question_v1(clarification_question)
    return validate_user_interrupt_v1(
        {
            "schema_version": 1,
            "interrupt_kind": "CONFIRMATION",
            "resume_kind": "CONFIRMATION",
            "origin_target": question["origin_target"],
            "question": question["question"],
            "affected_field_paths": list(question["affected_field_paths"]),
            "reason_code": question["reason_code"],
            "known_context_summary": question["known_context_summary"],
            "options": [dict(option) for option in question["options"]],
        }
    )


def load_request_understanding_classify_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "request_understanding.classify",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_request_understanding_clarify_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "request_understanding.clarify",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def _classify_valid_intent(
    *,
    intent: RequestIntentV1,
    llm_result: StructuredLLMResult,
) -> RequestUnderstandingOutputV1:
    validator_codes: list[str] = []
    unsupported = intent["unsupported_scope"]
    if unsupported["is_unsupported"]:
        validator_codes.append("INTENT_UNSUPPORTED_SCOPE")
        return RequestUnderstandingOutputV1(
            schema_version=1,
            result=RequestUnderstandingResult.INVALID.value,
            request_intent=None,
            clarification=None,
            failure={
                "schema_version": 1,
                "reason_code": unsupported["reason_code"] or "INTENT_UNSUPPORTED_SCOPE",
                "user_safe_message": unsupported["explanation"]
                or "이 요청은 현재 제품 범위에서 처리할 수 없습니다.",
                "diagnostic": "RequestIntentV1.unsupported_scope.is_unsupported=true",
            },
            validator_codes=validator_codes,
            llm_provider_result=_provider_summary(llm_result),
        )

    if intent["ambiguity"]["is_ambiguous"]:
        if not intent["ambiguity"]["items"]:
            raise RequestUnderstandingValidationError(
                "$.ambiguity.items is required when is_ambiguous is true"
            )
        validator_codes.append("INTENT_AMBIGUITY_DETECTED")
        return RequestUnderstandingOutputV1(
            schema_version=1,
            result=RequestUnderstandingResult.NEEDS_CONFIRMATION.value,
            request_intent=intent,
            clarification=_build_clarification(intent),
            failure=None,
            validator_codes=validator_codes,
            llm_provider_result=_provider_summary(llm_result),
        )

    if not _non_empty(intent["goal"]["summary"]):
        validator_codes.append("INTENT_GOAL_MISSING")
        return _confirmation_for_missing_field(
            intent=intent,
            field_path="goal.summary",
            reason_code="INTENT_GOAL_MISSING",
            question="무엇을 도와드리면 될지 조금 더 구체적으로 알려주세요.",
            validator_codes=validator_codes,
            llm_result=llm_result,
        )
    if not _non_empty(intent["goal"]["user_visible_objective"]):
        validator_codes.append("INTENT_GOAL_MISSING")
        return _confirmation_for_missing_field(
            intent=intent,
            field_path="goal.user_visible_objective",
            reason_code="INTENT_GOAL_MISSING",
            question="요청의 목표를 사용자에게 확인할 수 있도록 다시 알려주세요.",
            validator_codes=validator_codes,
            llm_result=llm_result,
        )
    if not any(_non_empty(item) for item in intent["completion_criteria"]):
        validator_codes.append("INTENT_COMPLETION_CRITERIA_MISSING")
        return _confirmation_for_missing_field(
            intent=intent,
            field_path="completion_criteria",
            reason_code="INTENT_COMPLETION_CRITERIA_MISSING",
            question="완료되었다고 판단할 기준을 알려주세요.",
            validator_codes=validator_codes,
            llm_result=llm_result,
        )

    validator_codes.append("REQUEST_INTENT_COMPLETE")
    return RequestUnderstandingOutputV1(
        schema_version=1,
        result=RequestUnderstandingResult.COMPLETE.value,
        request_intent=intent,
        clarification=None,
        failure=None,
        validator_codes=validator_codes,
        llm_provider_result=_provider_summary(llm_result),
    )


def _confirmation_for_missing_field(
    *,
    intent: RequestIntentV1,
    field_path: str,
    reason_code: str,
    question: str,
    validator_codes: list[str],
    llm_result: StructuredLLMResult,
) -> RequestUnderstandingOutputV1:
    return RequestUnderstandingOutputV1(
        schema_version=1,
        result=RequestUnderstandingResult.NEEDS_CONFIRMATION.value,
        request_intent=intent,
        clarification={
            "schema_version": 1,
            "origin_target": "request_understanding.classify",
            "question": question,
            "affected_field_paths": [field_path],
            "reason_code": reason_code,
            "known_context_summary": intent["goal"]["user_visible_objective"]
            or intent["goal"]["summary"],
            "options": [],
        },
        failure=None,
        validator_codes=validator_codes,
        llm_provider_result=_provider_summary(llm_result),
    )


def _build_clarification(intent: RequestIntentV1) -> ClarificationQuestionV1:
    first = intent["ambiguity"]["items"][0]
    return {
        "schema_version": 1,
        "origin_target": "request_understanding.classify",
        "question": first["user_question"],
        "affected_field_paths": [item["field_path"] for item in intent["ambiguity"]["items"]],
        "reason_code": first["reason_code"],
        "known_context_summary": intent["goal"]["user_visible_objective"]
        or intent["goal"]["summary"],
        "options": [],
    }


def _prompt_input_from_request(request: WorkflowStartRequest) -> dict[str, object]:
    return {
        "request_text": request.request_text,
        "entry_mode": request.entry_mode,
        "selected_resource_ids": list(request.selected_resource_ids),
    }


def _phase_for_result(result: RequestUnderstandingResult) -> WorkflowPhase:
    if result is RequestUnderstandingResult.INVALID:
        return WorkflowPhase.FINALIZE
    return WorkflowPhase.REQUEST_ANALYSIS


def resolve_confirmation_origin_target(
    *,
    user_interrupt: UserInterruptV1,
    response: ConfirmationResponseV1,
) -> str:
    question = validate_user_interrupt_v1(user_interrupt)
    normalized = validate_confirmation_response_v1(response)
    if normalized["response_kind"] == "OPTION_SELECTION":
        allowed_ids = {option["option_id"] for option in question["options"]}
        for option_id in normalized["selected_option_ids"]:
            if option_id not in allowed_ids:
                raise RequestUnderstandingValidationError(
                    f"unknown clarification option_id: {option_id}"
                )
    return question["origin_target"]


def _validate_goal(value: object) -> RequestIntentGoalV1:
    goal = _require_mapping(value, "$.goal")
    _require_exact_keys(goal, "$.goal", {"summary", "user_visible_objective"})
    return {
        "summary": _require_string(goal, "summary", "$.goal"),
        "user_visible_objective": _require_string(goal, "user_visible_objective", "$.goal"),
    }


def _validate_semantic_constraints(value: object) -> RequestIntentSemanticConstraintsV1:
    constraints = _require_mapping(value, "$.semantic_constraints")
    _require_exact_keys(
        constraints,
        "$.semantic_constraints",
        {
            "topics",
            "people",
            "time",
            "sources",
            "status_or_state",
            "negative_constraints",
            "policy_or_safety_constraints",
        },
    )
    return {
        "topics": [
            _validate_topic(item, f"$.semantic_constraints.topics[{index}]")
            for index, item in enumerate(_require_list(constraints["topics"], "$.topics"))
        ],
        "people": [
            _validate_person(item, f"$.semantic_constraints.people[{index}]")
            for index, item in enumerate(_require_list(constraints["people"], "$.people"))
        ],
        "time": [
            _validate_time(item, f"$.semantic_constraints.time[{index}]")
            for index, item in enumerate(_require_list(constraints["time"], "$.time"))
        ],
        "sources": [
            _validate_source(item, f"$.semantic_constraints.sources[{index}]")
            for index, item in enumerate(_require_list(constraints["sources"], "$.sources"))
        ],
        "status_or_state": [
            _validate_status(item, f"$.semantic_constraints.status_or_state[{index}]")
            for index, item in enumerate(_require_list(constraints["status_or_state"], "$.status"))
        ],
        "negative_constraints": _require_string_list(
            constraints["negative_constraints"],
            "$.semantic_constraints.negative_constraints",
        ),
        "policy_or_safety_constraints": _require_string_list(
            constraints["policy_or_safety_constraints"],
            "$.semantic_constraints.policy_or_safety_constraints",
        ),
    }


def _validate_topic(value: object, path: str) -> RequestIntentTopicConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"text", "source_text"})
    return {
        "text": _require_string(item, "text", path),
        "source_text": _require_string(item, "source_text", path),
    }


def _validate_person(value: object, path: str) -> RequestIntentPeopleConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"mention", "role_hint", "source_text"})
    role_hint = item["role_hint"]
    if role_hint is not None and not isinstance(role_hint, str):
        raise RequestUnderstandingValidationError(f"{path}.role_hint must be string or null")
    return {
        "mention": _require_string(item, "mention", path),
        "role_hint": role_hint,
        "source_text": _require_string(item, "source_text", path),
    }


def _validate_time(value: object, path: str) -> RequestIntentTimeConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"mention", "granularity_hint", "source_text"})
    granularity = _require_string(item, "granularity_hint", path)
    if granularity not in _TIME_GRANULARITY_VALUES:
        raise RequestUnderstandingValidationError(f"{path}.granularity_hint is invalid")
    return {
        "mention": _require_string(item, "mention", path),
        "granularity_hint": cast(
            Literal["DATE", "DATETIME", "RANGE", "RELATIVE", "UNKNOWN"],
            granularity,
        ),
        "source_text": _require_string(item, "source_text", path),
    }


def _validate_source(value: object, path: str) -> RequestIntentSourceConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"source", "mention", "confidence"})
    source = _require_string(item, "source", path)
    confidence = _require_string(item, "confidence", path)
    if source not in _SOURCE_VALUES:
        raise RequestUnderstandingValidationError(f"{path}.source is invalid")
    if confidence not in _CONFIDENCE_VALUES:
        raise RequestUnderstandingValidationError(f"{path}.confidence is invalid")
    return {
        "source": cast(Literal["GMAIL", "TASKS", "CALENDAR", "UNKNOWN"], source),
        "mention": _require_string(item, "mention", path),
        "confidence": cast(Literal["HIGH", "MEDIUM", "LOW"], confidence),
    }


def _validate_status(value: object, path: str) -> RequestIntentStatusConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"mention", "source_text"})
    return {
        "mention": _require_string(item, "mention", path),
        "source_text": _require_string(item, "source_text", path),
    }


def _validate_ambiguity(value: object) -> RequestIntentAmbiguityV1:
    ambiguity = _require_mapping(value, "$.ambiguity")
    _require_exact_keys(ambiguity, "$.ambiguity", {"is_ambiguous", "items"})
    is_ambiguous = ambiguity["is_ambiguous"]
    if not isinstance(is_ambiguous, bool):
        raise RequestUnderstandingValidationError("$.ambiguity.is_ambiguous must be boolean")
    return {
        "is_ambiguous": is_ambiguous,
        "items": [
            _validate_ambiguity_item(item, f"$.ambiguity.items[{index}]")
            for index, item in enumerate(_require_list(ambiguity["items"], "$.ambiguity.items"))
        ],
    }


def _validate_ambiguity_item(value: object, path: str) -> RequestIntentAmbiguityItemV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"field_path", "reason_code", "user_question"})
    return {
        "field_path": _require_string(item, "field_path", path),
        "reason_code": _require_string(item, "reason_code", path),
        "user_question": _require_string(item, "user_question", path),
    }


def _validate_unsupported_scope(value: object) -> RequestIntentUnsupportedScopeV1:
    unsupported = _require_mapping(value, "$.unsupported_scope")
    _require_exact_keys(
        unsupported,
        "$.unsupported_scope",
        {"is_unsupported", "reason_code", "explanation"},
    )
    is_unsupported = unsupported["is_unsupported"]
    if not isinstance(is_unsupported, bool):
        raise RequestUnderstandingValidationError(
            "$.unsupported_scope.is_unsupported must be boolean"
        )
    reason_code = unsupported["reason_code"]
    explanation = unsupported["explanation"]
    if reason_code is not None and not isinstance(reason_code, str):
        raise RequestUnderstandingValidationError(
            "$.unsupported_scope.reason_code must be string or null"
        )
    if explanation is not None and not isinstance(explanation, str):
        raise RequestUnderstandingValidationError(
            "$.unsupported_scope.explanation must be string or null"
        )
    return {
        "is_unsupported": is_unsupported,
        "reason_code": reason_code,
        "explanation": explanation,
    }


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=RequestUnderstandingValidationError)
_require_exact_keys = partial(
    _schema.require_exact_keys, error_cls=RequestUnderstandingValidationError
)
_require_allowed_keys = partial(
    _schema.require_allowed_keys, error_cls=RequestUnderstandingValidationError
)
_require_int = partial(_schema.require_int, error_cls=RequestUnderstandingValidationError)
_require_string = partial(_schema.require_string, error_cls=RequestUnderstandingValidationError)
_require_list = partial(_schema.require_list, error_cls=RequestUnderstandingValidationError)
_require_string_list = partial(
    _schema.require_string_list, error_cls=RequestUnderstandingValidationError
)
_provider_summary = _schema.provider_summary


def _non_empty(value: str) -> bool:
    return bool(value.strip())
