from __future__ import annotations

from pathlib import Path

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

DETECT_AMBIGUITY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-ambiguity-v1",
    json_schema={
        "type": "object",
        "required": [
            "requires_confirmation",
            "missing_information_owner",
            "reason_codes",
            "missing_fields",
        ],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {"requires_confirmation": {"const": False}},
                    "required": ["requires_confirmation"],
                },
                "then": {
                    "properties": {
                        "missing_information_owner": {"const": "NONE"},
                        "reason_codes": {"maxItems": 0},
                        "missing_fields": {"maxItems": 0},
                    }
                },
                "else": {
                    "properties": {
                        "missing_information_owner": {"const": "USER"},
                        "reason_codes": {"minItems": 1},
                        "missing_fields": {"minItems": 1},
                    }
                },
            }
        ],
        "properties": {
            "requires_confirmation": {
                "type": "boolean",
                "description": (
                    "False unless an explicit user-owned choice is genuinely missing. "
                    "When false, owner must be NONE and both arrays must be empty."
                ),
            },
            "missing_information_owner": {
                "enum": ["NONE", "USER", "CONNECTOR"],
                "description": (
                    "NONE when nothing is missing; USER only for a user-owned choice; "
                    "CONNECTOR for facts retrievable from selected or routed resources."
                ),
            },
            "reason_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Empty whenever requires_confirmation is false.",
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Empty whenever requires_confirmation is false.",
            },
        },
    },
)

def detect_ambiguity(
    *,
    llm_runtime: StructuredInferencePort,
    request: WorkflowStartRequest,
    goal_candidate: RequestGoalCandidateV1,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> AmbiguityV1:
    """Decide only current-Run, user-owned ambiguity."""
    if _is_bound_selected_read(request=request, goal_candidate=goal_candidate):
        return {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.detect_ambiguity",
        manifest_path or default_prompt_manifest_path(),
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "goal_candidate": dict(goal_candidate),
        "selected_resource_refs": [
            {
                "source": item.source,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "parent_resource_id": item.parent_resource_id,
            }
            for item in request.selected_resources
        ],
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    result = llm_runtime.infer(
        request.requested_mode,
        resolved_prompt_ref,
        prompt_input,
        DETECT_AMBIGUITY_OUTPUT_SCHEMA,
    )
    return _validate_ambiguity(result.structured_output)


def _validate_ambiguity(value: object) -> AmbiguityV1:
    if not isinstance(value, dict) or set(value) != {
        "requires_confirmation",
        "missing_information_owner",
        "reason_codes",
        "missing_fields",
    }:
        raise ValueError("request ambiguity fields are invalid")
    requires_confirmation = value.get("requires_confirmation")
    missing_information_owner = value.get("missing_information_owner")
    reason_codes = value.get("reason_codes")
    missing_fields = value.get("missing_fields")
    if not isinstance(requires_confirmation, bool):
        raise ValueError("requires_confirmation must be boolean")
    if missing_information_owner not in {"NONE", "USER", "CONNECTOR"}:
        raise ValueError("missing_information_owner is invalid")
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must contain strings")
    if not isinstance(missing_fields, list) or any(
        not isinstance(item, str) for item in missing_fields
    ):
        raise ValueError("missing_fields must contain strings")
    if requires_confirmation and (not reason_codes or not missing_fields):
        raise ValueError("reason_codes and missing_fields are required for missing information")
    if requires_confirmation and missing_information_owner == "NONE":
        raise ValueError("missing information requires an owner")
    if not requires_confirmation and (
        missing_information_owner != "NONE" or reason_codes or missing_fields
    ):
        raise ValueError("non-confirmation ambiguity metadata must be empty")
    if missing_information_owner == "CONNECTOR":
        return {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    return {
        "requires_confirmation": requires_confirmation,
        "reason_codes": reason_codes,
        "missing_fields": missing_fields,
    }


def _is_bound_selected_read(
    *, request: WorkflowStartRequest, goal_candidate: RequestGoalCandidateV1
) -> bool:
    return (
        request.entry_mode == "RESOURCE_SELECTED"
        and bool(request.selected_resources)
        and set(goal_candidate["requested_effect_hints"]) == {"READ"}
        and goal_candidate["analysis_requirement"] == "NONE"
    )
