"""Request-understanding workflow node implementation."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final, Literal, cast

import google_work_agent.application.orchestration._schema_support as _schema
from google_work_agent.application.orchestration.contracts import (
    CONFIRMATION_ORIGIN_TARGETS,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    RequestUnderstandingResult,
    UserInterruptV1,
    WorkflowPhase,
    validate_confirmation_origin_target,
    validate_confirmation_response_projection_v1,
    validate_user_interrupt_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AmbiguityV1,
    ClarificationOptionV1,
    ClarificationQuestionV1,
    ConstraintKindValue,
    ConstraintV1,
    RequestIntentV2,
    RequestUnderstandingOutputV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    RequestUnderstandingFailureV1 as RequestUnderstandingFailureV1,
)
from google_work_agent.application.orchestration.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.orchestration.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

JsonObject = dict[str, object]


REQUEST_INTENT_SCHEMA_VERSION: Final = 2
CLARIFICATION_QUESTION_SCHEMA_VERSION: Final = 1
REQUEST_UNDERSTANDING_OUTPUT_SCHEMA_VERSION: Final = 1
_CONSTRAINT_KIND_VALUES = {
    "PERSON",
    "EMAIL",
    "DATE",
    "TIME",
    "RESOURCE",
    "SCOPE",
    "USER_REQUIREMENT",
}
REQUEST_INTENT_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-intent-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "goal",
            "completion_conditions",
            "constraints",
            "requested_effect_hints",
            "requested_resource_hints",
            "analysis_requirement",
            "ambiguity",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [REQUEST_INTENT_SCHEMA_VERSION]},
            "goal": {"type": "string"},
            "completion_conditions": {"type": "array", "items": {"type": "string"}},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "field", "value"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": sorted(_CONSTRAINT_KIND_VALUES)},
                        "field": {"type": "string"},
                        "value": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                    },
                },
            },
            "requested_effect_hints": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"],
                },
            },
            "requested_resource_hints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "analysis_requirement": {
                "type": "string",
                "enum": ["NONE", "REQUIRED"],
            },
            "ambiguity": {
                "type": "object",
                "required": ["requires_confirmation", "reason_codes", "missing_fields"],
                "additionalProperties": False,
                "properties": {
                    "requires_confirmation": {"type": "boolean"},
                    "reason_codes": {"type": "array", "items": {"type": "string"}},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                },
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


class RequestUnderstandingValidationError(ValueError):
    """Raised when a structured RequestIntentV2 is not semantically usable."""


class RequestUnderstandingAgent:
    """Classify a workflow start request into the RequestIntentV2 handoff."""

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
        # Resolved lazily (see _clarify_prompt_ref below): clarify() is not
        # wired into the active SIX_ROLE_BASELINE subgraph node today, so
        # construction must not fail just because request_understanding.clarify
        # happens to be unavailable in the current prompt bundle.
        self._clarify_prompt_ref_override = clarify_prompt_ref
        self._manifest_path = manifest_path

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    @property
    def _clarify_prompt_ref(self) -> PromptReference:
        return self._clarify_prompt_ref_override or (
            load_request_understanding_clarify_prompt_reference(self._manifest_path)
        )

    def __call__(self, request: WorkflowStartRequest) -> RequestUnderstandingOutputV1:
        return self.classify(request)

    def classify(
        self,
        request: WorkflowStartRequest,
        *,
        confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    ) -> RequestUnderstandingOutputV1:
        llm_result = self.invoke_classify_llm(request, confirmation_response=confirmation_response)
        return self.build_output_from_llm_result(llm_result)

    def invoke_classify_llm(
        self,
        request: WorkflowStartRequest,
        *,
        confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=_prompt_input_from_request(
                request, confirmation_response=confirmation_response
            ),
            output_schema=REQUEST_INTENT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:request_understanding.classify",
            ),
            semantic_validate=validate_request_intent_v2,
        )

    def build_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
    ) -> RequestUnderstandingOutputV1:
        intent = validate_request_intent_v2(llm_result.structured_output)
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


def validate_request_intent_v2(value: object) -> RequestIntentV2:
    """Validate the LLM's RequestIntentV2 candidate (06-agent-workflow.md §3.1).

    ``meta`` is intentionally absent here: it is Application-owned lineage
    identity (artifact_id/revision/based_on), not something the LLM
    produces. ``materialize_request_intent_artifact`` attaches it right
    after this validation succeeds, so the returned value is a genuine
    ``RequestIntentV2`` only once both steps have run.
    """

    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "goal",
            "completion_conditions",
            "constraints",
            "requested_effect_hints",
            "requested_resource_hints",
            "analysis_requirement",
            "ambiguity",
        },
    )
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != REQUEST_INTENT_SCHEMA_VERSION:
        raise RequestUnderstandingValidationError(
            f"$.schema_version must be {REQUEST_INTENT_SCHEMA_VERSION}"
        )
    goal = _require_string(root, "goal", "$")
    completion_conditions = _require_string_list(
        root["completion_conditions"], "$.completion_conditions"
    )
    constraints = [
        _validate_constraint(item, f"$.constraints[{index}]")
        for index, item in enumerate(_require_list(root["constraints"], "$.constraints"))
    ]
    ambiguity = _validate_ambiguity(root["ambiguity"])
    return cast(
        RequestIntentV2,
        {
            "schema_version": REQUEST_INTENT_SCHEMA_VERSION,
            "goal": goal,
            "completion_conditions": completion_conditions,
            "constraints": constraints,
            "requested_effect_hints": cast(
                list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]],
                _require_enum_list(
                    root["requested_effect_hints"],
                    "$.requested_effect_hints",
                    {"READ", "CREATE", "UPDATE", "SEND", "DELETE"},
                ),
            ),
            "requested_resource_hints": _require_string_list(
                root["requested_resource_hints"], "$.requested_resource_hints"
            ),
            "analysis_requirement": cast(
                Literal["NONE", "REQUIRED"],
                _require_enum_string(root, "analysis_requirement", "$", {"NONE", "REQUIRED"}),
            ),
            "ambiguity": ambiguity,
        },
    )


def materialize_request_intent_artifact(
    intent: RequestIntentV2,
    *,
    artifact_id: str,
) -> RequestIntentV2:
    """Attach Application-owned artifact identity after LLM validation."""

    return {
        **intent,
        "meta": {"artifact_id": artifact_id, "revision": 1, "based_on": []},
    }


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
    intent: RequestIntentV2,
    llm_result: StructuredLLMResult,
) -> RequestUnderstandingOutputV1:
    """Route a validated RequestIntentV2 candidate to its Node result.

    Q2-X: RequestIntentV2 no longer carries ``unsupported_scope`` --
    Request Understanding does not judge product-capability support
    anymore. A request whose resource/effect combination the Registry
    cannot serve (e.g. deleting a Gmail message, which has no eligible
    tool) still classifies COMPLETE here with its hints preserved, and is
    deterministically BLOCKED downstream by Tool Route's Signed Registry
    binding (``ToolRouteCoordinator._eligible_bindings``). ``ambiguity`` is
    reserved for meaning only the user can resolve (e.g. "which Kim?");
    unsupported-capability judgment never returns NEEDS_CONFIRMATION here.
    """

    validator_codes: list[str] = []

    if intent["ambiguity"]["requires_confirmation"]:
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

    if not _non_empty(intent["goal"]):
        validator_codes.append("INTENT_GOAL_MISSING")
        return _confirmation_for_missing_field(
            intent=intent,
            field_path="goal",
            reason_code="INTENT_GOAL_MISSING",
            question="무엇을 도와드리면 될지 조금 더 구체적으로 알려주세요.",
            validator_codes=validator_codes,
            llm_result=llm_result,
        )
    if not any(_non_empty(item) for item in intent["completion_conditions"]):
        validator_codes.append("INTENT_COMPLETION_CRITERIA_MISSING")
        return _confirmation_for_missing_field(
            intent=intent,
            field_path="completion_conditions",
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
    intent: RequestIntentV2,
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
            "known_context_summary": intent["goal"],
            "options": [],
        },
        failure=None,
        validator_codes=validator_codes,
        llm_provider_result=_provider_summary(llm_result),
    )


def _build_clarification(intent: RequestIntentV2) -> ClarificationQuestionV1:
    """Deterministic clarification text from an ambiguity signal.

    RequestIntentV2.ambiguity carries structured ``reason_codes``/
    ``missing_fields`` only -- unlike retired V1, no per-item natural-language
    ``user_question`` field exists for the LLM to fill in directly (that is
    ``request_understanding.clarify``'s job in Canonical, not yet wired into
    the active SIX_ROLE_BASELINE path). This builds a generic but honest
    question from the structured fields rather than inventing free text.
    """

    ambiguity = intent["ambiguity"]
    missing_fields = ambiguity["missing_fields"]
    question = (
        f"다음 정보를 확인해 주세요: {', '.join(missing_fields)}"
        if missing_fields
        else "요청을 진행하기 전에 조금 더 구체적으로 알려주세요."
    )
    return {
        "schema_version": 1,
        "origin_target": "request_understanding.classify",
        "question": question,
        "affected_field_paths": missing_fields,
        "reason_code": ambiguity["reason_codes"][0]
        if ambiguity["reason_codes"]
        else "INTENT_AMBIGUITY_MISSED",
        "known_context_summary": intent["goal"],
        "options": [],
    }


_SELECTED_RESOURCE_SOURCE_TO_CATEGORY: Final = {
    "GMAIL": "EMAIL",
    "TASKS": "TASK",
    "CALENDAR": "CALENDAR",
}

# P0 has exactly one Connector (docs/03-system-architecture.md: "P0 첫
# Connector는 google_workspace"). request_understanding.classify's
# selected_resources projection needs a connector_id per
# prompt-runtime-input-contract-v1.json; there is only one to report until
# a second Connector exists.
_P0_CONNECTOR_ID: Final = "google_workspace"


def _prompt_input_from_request(
    request: WorkflowStartRequest,
    *,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> dict[str, object]:
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "entry_mode": request.entry_mode,
        # MISSING_UPSTREAM_FIELD: no deterministic request-language source
        # exists anywhere upstream of this node yet (WorkflowStartRequest,
        # conversation/run state). request-understanding-input-v1.schema.json
        # types this as ["string", "null"] for exactly this case -- send
        # null rather than guess a value or add a new LLM call to detect it.
        "language": None,
        "selected_resources": [
            {
                "connector_id": _P0_CONNECTOR_ID,
                "resource_type": _SELECTED_RESOURCE_SOURCE_TO_CATEGORY.get(ref.source, ref.source),
                "external_resource_id": ref.resource_id,
            }
            for ref in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        # Pre-Prompt Runtime Closure: the already-canonical, already-bounded
        # ConfirmationResponseProjectionV1 (schema_version/response_kind/
        # selected_option/free_text -- see validate_confirmation_response_projection_v1)
        # is the only thing that crosses this boundary on a WAITING_CONFIRMATION
        # resume. The raw interrupt resume_payload dict is never forwarded
        # as-is; it is always re-validated into this bounded shape first
        # (see _classify_node in subgraphs/request_understanding.py).
        prompt_input["confirmation_response"] = dict(confirmation_response)
    return prompt_input


def _phase_for_result(result: RequestUnderstandingResult) -> WorkflowPhase:
    if result is RequestUnderstandingResult.INVALID:
        return WorkflowPhase.FINALIZE
    return WorkflowPhase.REQUEST_ANALYSIS


def resolve_confirmation_origin_target(
    *,
    user_interrupt: UserInterruptV1,
    response: ConfirmationResponseProjectionV1,
) -> str:
    question = validate_user_interrupt_v1(user_interrupt)
    normalized = validate_confirmation_response_projection_v1(response)
    if normalized["response_kind"] == "OPTION":
        allowed_ids = {option["option_id"] for option in question["options"]}
        selected_option = normalized["selected_option"]
        if selected_option not in allowed_ids:
            raise RequestUnderstandingValidationError(
                f"unknown clarification option_id: {selected_option}"
            )
    return question["origin_target"]


def _validate_constraint(value: object, path: str) -> ConstraintV1:
    item = _require_mapping(value, path)
    _require_exact_keys(item, path, {"kind", "field", "value"})
    kind = _require_string(item, "kind", path)
    if kind not in _CONSTRAINT_KIND_VALUES:
        raise RequestUnderstandingValidationError(f"{path}.kind is invalid")
    raw_value = item["value"]
    if isinstance(raw_value, str):
        value_out: str | list[str] = raw_value
    elif isinstance(raw_value, list) and all(isinstance(entry, str) for entry in raw_value):
        value_out = cast(list[str], raw_value)
    else:
        raise RequestUnderstandingValidationError(f"{path}.value must be a string or string array")
    return {
        "kind": cast(ConstraintKindValue, kind),
        "field": _require_string(item, "field", path),
        "value": value_out,
    }


def _validate_ambiguity(value: object) -> AmbiguityV1:
    ambiguity = _require_mapping(value, "$.ambiguity")
    _require_exact_keys(
        ambiguity, "$.ambiguity", {"requires_confirmation", "reason_codes", "missing_fields"}
    )
    requires_confirmation = ambiguity["requires_confirmation"]
    if not isinstance(requires_confirmation, bool):
        raise RequestUnderstandingValidationError(
            "$.ambiguity.requires_confirmation must be boolean"
        )
    reason_codes = _require_string_list(ambiguity["reason_codes"], "$.ambiguity.reason_codes")
    missing_fields = _require_string_list(ambiguity["missing_fields"], "$.ambiguity.missing_fields")
    if requires_confirmation and not reason_codes:
        raise RequestUnderstandingValidationError(
            "$.ambiguity.reason_codes is required when requires_confirmation is true"
        )
    return {
        "requires_confirmation": requires_confirmation,
        "reason_codes": reason_codes,
        "missing_fields": missing_fields,
    }


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=RequestUnderstandingValidationError)
_require_exact_keys = partial(
    _schema.require_exact_keys, error_cls=RequestUnderstandingValidationError
)
_require_int = partial(_schema.require_int, error_cls=RequestUnderstandingValidationError)
_require_string = partial(_schema.require_string, error_cls=RequestUnderstandingValidationError)
_require_list = partial(_schema.require_list, error_cls=RequestUnderstandingValidationError)
_require_string_list = partial(
    _schema.require_string_list, error_cls=RequestUnderstandingValidationError
)
_provider_summary = _schema.provider_summary


def _require_enum_list(value: object, path: str, allowed: set[str]) -> list[str]:
    items = _require_string_list(value, path)
    if any(item not in allowed for item in items):
        raise RequestUnderstandingValidationError(f"{path} contains an invalid value")
    return items


def _require_enum_string(
    value: dict[str, object],
    key: str,
    path: str,
    allowed: set[str],
) -> str:
    item = _require_string(value, key, path)
    if item not in allowed:
        raise RequestUnderstandingValidationError(f"{path}.{key} is invalid")
    return item


def _non_empty(value: str) -> bool:
    return bool(value.strip())
