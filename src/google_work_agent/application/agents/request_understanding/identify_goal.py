from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

IDENTIFY_GOAL_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-goal-candidate-v1",
    json_schema={
        "type": "object",
        "required": [
            "goal",
            "completion_conditions",
            "constraints",
            "requested_effect_hints",
            "requested_resource_hints",
            "analysis_requirement",
        ],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {
                        "requested_effect_hints": {"type": "array", "minItems": 1}
                    },
                    "required": ["requested_effect_hints"],
                },
                "then": {
                    "properties": {
                        "requested_resource_hints": {"type": "array", "minItems": 1}
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "requested_resource_hints": {"type": "array", "minItems": 1}
                    },
                    "required": ["requested_resource_hints"],
                },
                "then": {
                    "properties": {
                        "requested_effect_hints": {"type": "array", "minItems": 1}
                    }
                },
            },
        ],
        "properties": {
            "goal": {"type": "string"},
            "completion_conditions": {"type": "array", "items": {"type": "string"}},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "field", "value"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {
                            "enum": [
                                "PERSON",
                                "EMAIL",
                                "DATE",
                                "TIME",
                                "RESOURCE",
                                "SCOPE",
                                "USER_REQUIREMENT",
                            ]
                        },
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
                "items": {"enum": ["READ", "CREATE", "UPDATE", "SEND", "DELETE"]},
                "description": (
                    "Effects on Google Workspace resources only. Retrieving, summarizing, "
                    "or analyzing an existing resource is READ; producing an assistant "
                    "answer or summary is never CREATE. CREATE, UPDATE, SEND, and DELETE "
                    "apply only when the user requests that external effect, and an "
                    "explicitly forbidden effect must not appear. Identifying or analyzing "
                    "follow-up actions from existing material is READ unless the user also "
                    "explicitly asks to apply a write in Google Workspace."
                ),
            },
            "requested_resource_hints": {
                "type": "array",
                "items": {
                    "enum": [
                        "GMAIL_THREAD",
                        "GMAIL_MESSAGE",
                        "GMAIL_DRAFT",
                        "GMAIL_ATTACHMENT",
                        "TASK_LIST",
                        "TASK",
                        "CALENDAR",
                        "CALENDAR_EVENT",
                        "CALENDAR_FREEBUSY",
                    ]
                },
                "uniqueItems": True,
                "description": (
                    "Semantic resource concepts explicitly named or necessarily targeted. "
                    "Gmail or email lookup uses GMAIL_THREAD, Google Tasks work uses TASK, "
                    "and Google Calendar event work uses CALENDAR_EVENT. Empty only when "
                    "the request needs no Google Workspace resource."
                ),
            },
            "analysis_requirement": {
                "enum": ["NONE", "REQUIRED"],
                "description": (
                    "REQUIRED only for downstream business analysis such as relationships, "
                    "dependencies, conflicts, duplicates, follow-up actions, or operational "
                    "risk. A simple list, lookup, direct fact extraction, read, or summary is "
                    "NONE whether the resource is selected or retrieved. REQUIRED needs an "
                    "explicit request to analyze implications, comparisons, or next actions."
                ),
            },
        },
    },
)


def identify_goal(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> RequestGoalCandidateV1:
    """Identify only the current Run's goal semantics."""
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.identify_goal", manifest_path or default_prompt_manifest_path()
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "selected_resource_refs": [
            {
                "source": ref.source,
                "resource_type": ref.resource_type,
                "resource_id": ref.resource_id,
                "parent_resource_id": ref.parent_resource_id,
            }
            for ref in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    output_schema = _output_schema_for_request(request)
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        output_schema,
    )
    candidate = _apply_explicit_read_authority(
        _validate_goal_candidate(
            result.structured_output,
            schema=output_schema,
        ),
        request_text=request.request_text,
    )
    candidate = _apply_selected_resource_authority(candidate, request=request)
    return _validate_goal_candidate(candidate)


_EXPLICIT_READ_RESOURCE_PATTERNS = (
    (re.compile(r"(?i)(?<![a-z])google\s+tasks?(?![a-z])"), "TASK"),
    (re.compile(r"(?i)(?<![a-z])gmail(?![a-z])"), "GMAIL_THREAD"),
    (re.compile(r"(?i)(?<![a-z])google\s+calendar(?![a-z])"), "CALENDAR_EVENT"),
)
_EXPLICIT_READ_MARKERS = (
    "알려",
    "보여",
    "목록",
    "찾아",
    "읽어",
    "요약",
    "분석",
    "list",
    "find",
    "read",
    "show",
    "summarize",
    "analyse",
    "analyze",
)
_EXPLICIT_WRITE_MARKERS = (
    "만들",
    "생성",
    "추가",
    "수정",
    "변경",
    "삭제",
    "보내",
    "전송",
    "등록",
    "create",
    "add",
    "update",
    "modify",
    "delete",
    "send",
)


def _output_schema_for_request(request: WorkflowStartRequest) -> OutputSchemaDefinition:
    """Let deterministic explicit-read authority complete paired hint fields."""

    if not (
        _has_explicit_read_authority(request.request_text)
        or _selected_resource_hints(request)
    ):
        return IDENTIFY_GOAL_OUTPUT_SCHEMA
    return OutputSchemaDefinition(
        schema_version=IDENTIFY_GOAL_OUTPUT_SCHEMA.schema_version,
        json_schema={
            key: value
            for key, value in IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema.items()
            if key != "allOf"
        },
    )


def _has_explicit_read_authority(request_text: str) -> bool:
    normalized = request_text.casefold()
    return (
        any(pattern.search(request_text) for pattern, _resource in _EXPLICIT_READ_RESOURCE_PATTERNS)
        and any(marker in normalized for marker in _EXPLICIT_READ_MARKERS)
        and not any(marker in normalized for marker in _EXPLICIT_WRITE_MARKERS)
    )


def _apply_explicit_read_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Preserve explicitly named Workspace reads when model hints are empty."""
    resources = list(candidate["requested_resource_hints"])
    for pattern, resource_type in _EXPLICIT_READ_RESOURCE_PATTERNS:
        if pattern.search(request_text) and resource_type not in resources:
            resources.append(resource_type)
    if not resources or candidate["requested_effect_hints"]:
        return {**candidate, "requested_resource_hints": resources}
    if not _has_explicit_read_authority(request_text):
        return {**candidate, "requested_resource_hints": resources}
    return {
        **candidate,
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": resources,
    }


def _apply_selected_resource_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Preserve trusted UI selection facts outside model-owned semantics."""
    if request.entry_mode != "RESOURCE_SELECTED" or not request.selected_resources:
        return candidate

    resource_ids = list(dict.fromkeys(ref.resource_id for ref in request.selected_resources))
    constraints = list(candidate["constraints"])
    constrained_resource_ids = {
        str(item)
        for constraint in constraints
        if constraint["kind"] == "RESOURCE"
        for item in (
            constraint["value"]
            if isinstance(constraint["value"], list)
            else [constraint["value"]]
        )
    }
    missing_resource_ids = [
        resource_id for resource_id in resource_ids if resource_id not in constrained_resource_ids
    ]
    if missing_resource_ids:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "selected_resource_id",
                "value": missing_resource_ids,
            }
        )

    effects = list(candidate["requested_effect_hints"])
    if "READ" not in effects:
        effects.insert(0, "READ")
    resource_hints = list(candidate["requested_resource_hints"])
    for hint in _selected_resource_hints(request):
        if hint not in resource_hints:
            resource_hints.append(hint)
    return {
        **candidate,
        "constraints": constraints,
        "requested_effect_hints": effects,
        "requested_resource_hints": resource_hints,
    }


_SELECTED_RESOURCE_HINTS = {
    ("GMAIL", "THREAD"): "GMAIL_THREAD",
    ("GMAIL", "MESSAGE"): "GMAIL_MESSAGE",
    ("GMAIL", "DRAFT"): "GMAIL_DRAFT",
    ("GMAIL", "ATTACHMENT"): "GMAIL_ATTACHMENT",
    ("TASKS", "TASK_LIST"): "TASK_LIST",
    ("TASKS", "TASK"): "TASK",
    ("CALENDAR", "CALENDAR"): "CALENDAR",
    ("CALENDAR", "EVENT"): "CALENDAR_EVENT",
    ("CALENDAR", "FREEBUSY"): "CALENDAR_FREEBUSY",
}


def _selected_resource_hints(request: WorkflowStartRequest) -> list[str]:
    return list(
        dict.fromkeys(
            hint
            for ref in request.selected_resources
            for hint in (
                _SELECTED_RESOURCE_HINTS.get(
                    (ref.source.upper(), ref.resource_type.upper())
                ),
            )
            if hint is not None
        )
    )


def _validate_goal_candidate(
    value: object,
    *,
    schema: OutputSchemaDefinition = IDENTIFY_GOAL_OUTPUT_SCHEMA,
) -> RequestGoalCandidateV1:
    errors = validate_output_schema(value, schema.json_schema)
    if errors:
        raise ValueError(f"request goal candidate is invalid: {'; '.join(errors)}")
    return cast(RequestGoalCandidateV1, value)
