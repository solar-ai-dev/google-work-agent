from __future__ import annotations

import re
from copy import deepcopy
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

from .preserve_vague_read_semantics import preserve_vague_read_semantics

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
    candidate = _apply_quoted_literal_authority(
        _validate_goal_candidate(result.structured_output, schema=output_schema),
        request_text=request.request_text,
    )
    candidate = _apply_explicit_read_authority(candidate, request_text=request.request_text)
    candidate = preserve_vague_read_semantics(
        candidate,
        request_text=request.request_text,
        entry_mode=request.entry_mode,
    )
    candidate = _apply_general_answer_only_authority(candidate, request=request)
    candidate = _apply_selected_resource_authority(candidate, request=request)
    return _validate_goal_candidate(candidate)


_EXPLICIT_READ_RESOURCE_PATTERNS = (
    (re.compile(r"(?i)(?<![a-z])google\s+tasks?(?![a-z])"), "TASK"),
    (re.compile(r"(?i)(?<![a-z])gmail(?![a-z])"), "GMAIL_THREAD"),
    (re.compile(r"(?i)(?<![a-z])e-?mail(?![a-z])|메일"), "GMAIL_THREAD"),
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
_EXPLICIT_ANALYSIS_MARKERS = (
    "분석",
    "비교",
    "결정",
    "결론",
    "영향",
    "원인",
    "리스크",
    "관계",
    "analy",
    "compare",
    "decision",
    "conclusion",
    "impact",
    "risk",
)
_GENERAL_ANSWER_ONLY_CONTENT_MARKERS = (
    "원칙",
    "방법",
    "팁",
    "조언",
    "개념",
    "기준",
    "principle",
    "guideline",
    "best practice",
    "advice",
    "tip",
    "concept",
)
_GENERAL_ANSWER_ONLY_RESPONSE_MARKERS = (
    "알려",
    "설명",
    "말해",
    "답해",
    "explain",
    "tell",
    "answer",
)
_CURRENT_WORKSPACE_FACT_MARKERS = (
    "내 ",
    "나의",
    "현재",
    "최근",
    "선택한",
    "찾아",
    "읽어",
    "목록",
    "요약",
    "분석",
    "my ",
    "current",
    "recent",
    "selected",
    "find",
    "read",
    "list",
    "summarize",
    "analyse",
    "analyze",
)
_QUOTED_LITERAL_PATTERNS = (
    re.compile(r"'[^']*'"),
    re.compile(r'"[^"]*"'),
    re.compile(r"‘[^’]*’"),
    re.compile(r"“[^”]*”"),
)
_EXPLICIT_DATE_SIGNAL = re.compile(
    r"(?i)(?:"
    r"\d{1,4}\s*(?:년|[-./])\s*\d{1,2}"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|오늘|내일|모레|이번\s*주|다음\s*주|다음\s*달|주말"
    r"|월요일|화요일|수요일|목요일|금요일|토요일|일요일"
    r"|까지|마감|기한|날짜|due|deadline|today|tomorrow|next\s+(?:week|month)"
    r")"
)


def _apply_quoted_literal_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Do not reinterpret a quoted resource literal as an unstated date."""

    outside_literals = request_text
    quoted_literals: list[str] = []
    for pattern in _QUOTED_LITERAL_PATTERNS:
        quoted_literals.extend(pattern.findall(request_text))
        outside_literals = pattern.sub(" ", outside_literals)
    if not quoted_literals:
        return candidate
    outside_has_date_signal = _EXPLICIT_DATE_SIGNAL.search(outside_literals) is not None
    quoted_text = " ".join(quoted_literals)
    constraints = [
        constraint
        for constraint in candidate["constraints"]
        if constraint["kind"] != "DATE"
        or (
            outside_has_date_signal
            and (
                not _date_value_appears_in_text(constraint["value"], quoted_text)
                or _date_value_appears_in_text(constraint["value"], outside_literals)
            )
        )
    ]
    return {**candidate, "constraints": constraints}


def _date_value_appears_in_text(value: object, text: str) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        match = re.search(r"(?:\d{4}[-./])?(\d{1,2})[-./](\d{1,2})", item)
        if match is None:
            continue
        month, day = (int(match.group(1)), int(match.group(2)))
        token = re.compile(
            rf"(?<!\d)0?{month}\s*(?:[-./]|월\s*)0?{day}(?:\s*일)?(?!\d)"
        )
        if token.search(text):
            return True
    return False


def _output_schema_for_request(request: WorkflowStartRequest) -> OutputSchemaDefinition:
    """Let deterministic explicit-read authority complete paired hint fields."""

    has_explicit_read = _has_explicit_read_authority(request.request_text)
    if not (has_explicit_read or _selected_resource_hints(request)):
        return IDENTIFY_GOAL_OUTPUT_SCHEMA
    schema = cast(dict[str, object], deepcopy(IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema))
    schema.pop("allOf", None)
    if request.entry_mode == "AGENT_SEARCH" and has_explicit_read:
        constraints = cast(dict[str, object], schema["properties"])["constraints"]
        cast(dict[str, object], constraints)["minItems"] = 1
    return OutputSchemaDefinition(
        schema_version=IDENTIFY_GOAL_OUTPUT_SCHEMA.schema_version,
        json_schema=schema,
    )


def _has_explicit_read_authority(request_text: str) -> bool:
    normalized = request_text.casefold()
    return (
        bool(_explicit_read_resource_hints(request_text))
        and any(marker in normalized for marker in _EXPLICIT_READ_MARKERS)
        and not any(marker in normalized for marker in _EXPLICIT_WRITE_MARKERS)
    )


def _explicit_read_resource_hints(request_text: str) -> list[str]:
    return list(
        dict.fromkeys(
            resource_type
            for pattern, resource_type in _EXPLICIT_READ_RESOURCE_PATTERNS
            if pattern.search(request_text)
        )
    )


def is_general_answer_only_request(request_text: str) -> bool:
    """Recognize explicit advice/explanation requests that need no Workspace fact."""

    normalized = request_text.casefold()
    return (
        any(marker in normalized for marker in _GENERAL_ANSWER_ONLY_CONTENT_MARKERS)
        and any(marker in normalized for marker in _GENERAL_ANSWER_ONLY_RESPONSE_MARKERS)
        and not any(marker in normalized for marker in _CURRENT_WORKSPACE_FACT_MARKERS)
        and not any(marker in normalized for marker in _EXPLICIT_WRITE_MARKERS)
    )


def _apply_general_answer_only_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request: WorkflowStartRequest,
) -> RequestGoalCandidateV1:
    """Remove model-invented Workspace reads from explicit advice requests."""

    if (
        request.selected_resources
        or not is_general_answer_only_request(request.request_text)
        or any(effect != "READ" for effect in candidate["requested_effect_hints"])
    ):
        return candidate
    return {
        **candidate,
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }


def _apply_explicit_read_authority(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
) -> RequestGoalCandidateV1:
    """Preserve explicit reads and reject model-invented Workspace effects."""
    explicit_resources = _explicit_read_resource_hints(request_text)
    if _has_explicit_read_authority(request_text):
        return {
            **candidate,
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": explicit_resources,
            "analysis_requirement": (
                "REQUIRED"
                if _has_explicit_analysis_request(request_text)
                else candidate["analysis_requirement"]
            ),
        }
    resources = list(candidate["requested_resource_hints"])
    for resource_type in explicit_resources:
        if resource_type not in resources:
            resources.append(resource_type)
    return {
        **candidate,
        "requested_resource_hints": resources,
    }


def _has_explicit_analysis_request(request_text: str) -> bool:
    normalized = request_text.casefold()
    return any(marker in normalized for marker in _EXPLICIT_ANALYSIS_MARKERS)


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
