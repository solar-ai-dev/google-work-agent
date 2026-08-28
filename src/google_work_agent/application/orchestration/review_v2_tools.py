"""Native Tool Calling boundary for canonical Review V2 candidates.

The function name is the status discriminator.  Each function exposes only the
payload owned by its canonical PlanReviewResultV2 variant, so impossible
combinations such as PASS+confirmation or RETRIEVE_MORE+legacy issues are not
representable at the provider boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from google_work_agent.application.orchestration.inspect_plan_output import (
    PlanReviewCandidateV2,
    validate_plan_review_candidate_v2,
)
from google_work_agent.ports.llm import (
    ToolCallProviderResponse,
    ToolDefinition,
)

_STRING: Final = {"type": "string"}
_NON_EMPTY_STRING: Final = {"type": "string", "minLength": 1}

_REVIEW_ISSUE_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code", "description", "action_id"],
    "properties": {
        "code": _NON_EMPTY_STRING,
        "description": _STRING,
        "action_id": {"type": ["string", "null"]},
    },
}
_REVIEW_EVIDENCE_GAP_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code", "description", "required_information"],
    "properties": {
        "code": _NON_EMPTY_STRING,
        "description": _STRING,
        "required_information": {"type": "array", "items": _NON_EMPTY_STRING},
    },
}
_REVIEW_ROUTE_ISSUE_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code", "description", "route_id"],
    "properties": {
        "code": _NON_EMPTY_STRING,
        "description": _STRING,
        "route_id": {"type": ["string", "null"]},
    },
}
_REVIEW_CONFIRMATION_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reason_code", "question", "options"],
    "properties": {
        "reason_code": _NON_EMPTY_STRING,
        "question": _NON_EMPTY_STRING,
        "options": {"type": "array", "items": _NON_EMPTY_STRING},
    },
}
_REVIEW_BLOCKER_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code", "description"],
    "properties": {
        "code": _NON_EMPTY_STRING,
        "description": _STRING,
    },
}

REVIEW_V2_PASS_TOOL: Final = ToolDefinition(
    name="review_pass",
    description="The proposed answer/plan has no material defect.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["summary"],
        "properties": {"summary": _STRING},
    },
)
REVIEW_V2_REVISE_TOOL: Final = ToolDefinition(
    name="review_revise",
    description="A local Planning defect can be repaired from current evidence.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["issues"],
        "properties": {"issues": {"type": "array", "items": _REVIEW_ISSUE_SCHEMA}},
    },
)
REVIEW_V2_RETRIEVE_MORE_TOOL: Final = ToolDefinition(
    name="review_retrieve_more",
    description="Additional evidence from the current input routes is required.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_gaps"],
        "properties": {"evidence_gaps": {"type": "array", "items": _REVIEW_EVIDENCE_GAP_SCHEMA}},
    },
)
REVIEW_V2_ROUTE_RECONSIDERATION_TOOL: Final = ToolDefinition(
    name="review_route_reconsideration",
    description="The frozen route cannot satisfy the request.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["route_issues"],
        "properties": {"route_issues": {"type": "array", "items": _REVIEW_ROUTE_ISSUE_SCHEMA}},
    },
)
REVIEW_V2_CONFIRM_TOOL: Final = ToolDefinition(
    name="review_confirm",
    description="A user-owned decision is required before the workflow can proceed.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["confirmation"],
        "properties": {"confirmation": _REVIEW_CONFIRMATION_SCHEMA},
    },
)
REVIEW_V2_BLOCK_TOOL: Final = ToolDefinition(
    name="review_block",
    description="The supplied policy context establishes a blocking condition.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["blockers"],
        "properties": {"blockers": {"type": "array", "items": _REVIEW_BLOCKER_SCHEMA}},
    },
)

REVIEW_V2_INSPECT_TOOLS: Final = (
    REVIEW_V2_PASS_TOOL,
    REVIEW_V2_REVISE_TOOL,
    REVIEW_V2_RETRIEVE_MORE_TOOL,
    REVIEW_V2_ROUTE_RECONSIDERATION_TOOL,
    REVIEW_V2_CONFIRM_TOOL,
    REVIEW_V2_BLOCK_TOOL,
)
REVIEW_V2_RECHECK_TOOLS: Final = (REVIEW_V2_PASS_TOOL, REVIEW_V2_BLOCK_TOOL)

_TOOL_VARIANTS: Final[dict[str, tuple[str, str]]] = {
    "review_pass": ("PASS", "summary"),
    "review_revise": ("REVISE", "issues"),
    "review_retrieve_more": ("RETRIEVE_MORE", "evidence_gaps"),
    "review_route_reconsideration": ("ROUTE_RECONSIDERATION", "route_issues"),
    "review_confirm": ("CONFIRM", "confirmation"),
    "review_block": ("BLOCK", "blockers"),
}


class ReviewV2ToolCallError(ValueError):
    """Provider tool call does not encode exactly one canonical Review variant."""


def review_tool_call_to_candidate_v2(
    response: ToolCallProviderResponse,
) -> PlanReviewCandidateV2:
    if len(response.calls) != 1:
        raise ReviewV2ToolCallError(
            f"expected exactly one review tool call, got {len(response.calls)}"
        )
    call = response.calls[0]
    variant = _TOOL_VARIANTS.get(call.name)
    if variant is None:
        raise ReviewV2ToolCallError(f"unknown Review V2 tool: {call.name}")
    status, payload_key = variant
    arguments = _mapping(call.arguments)
    if set(arguments) != {payload_key}:
        raise ReviewV2ToolCallError(f"{call.name} arguments must contain only {payload_key}")
    candidate: dict[str, object] = {
        "schema_version": 2,
        "status": status,
        payload_key: arguments[payload_key],
    }
    try:
        return validate_plan_review_candidate_v2(candidate)
    except ValueError as error:
        raise ReviewV2ToolCallError(str(error)) from error


def _mapping(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReviewV2ToolCallError("review tool argument keys must be strings")
        result[key] = item
    return result


__all__ = [
    "REVIEW_V2_BLOCK_TOOL",
    "REVIEW_V2_CONFIRM_TOOL",
    "REVIEW_V2_INSPECT_TOOLS",
    "REVIEW_V2_PASS_TOOL",
    "REVIEW_V2_RECHECK_TOOLS",
    "REVIEW_V2_RETRIEVE_MORE_TOOL",
    "REVIEW_V2_REVISE_TOOL",
    "REVIEW_V2_ROUTE_RECONSIDERATION_TOOL",
    "ReviewV2ToolCallError",
    "review_tool_call_to_candidate_v2",
]
