from __future__ import annotations

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
                    "explicitly forbidden effect must not appear."
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
                    "risk. Reading or summarizing one selected resource is NONE, but an "
                    "explicit request to analyze its implications or next actions is REQUIRED."
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
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        IDENTIFY_GOAL_OUTPUT_SCHEMA,
    )
    return _apply_selected_resource_authority(
        _validate_goal_candidate(result.structured_output),
        request=request,
    )


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
    return {**candidate, "constraints": constraints, "requested_effect_hints": effects}


def _validate_goal_candidate(value: object) -> RequestGoalCandidateV1:
    errors = validate_output_schema(value, IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise ValueError(f"request goal candidate is invalid: {'; '.join(errors)}")
    return cast(RequestGoalCandidateV1, value)
