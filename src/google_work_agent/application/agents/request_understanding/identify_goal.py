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
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
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
            },
            "requested_resource_hints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "analysis_requirement": {"enum": ["NONE", "REQUIRED"]},
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
    result = llm_runtime.invoke_structured(
        prompt_ref=resolved_prompt_ref,
        prompt_input=prompt_input,
        output_schema=IDENTIFY_GOAL_OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:request.identify_goal",
        ),
        semantic_validate=_validate_goal_candidate,
    )
    return _validate_goal_candidate(result.structured_output)


def _validate_goal_candidate(value: object) -> RequestGoalCandidateV1:
    errors = validate_output_schema(value, IDENTIFY_GOAL_OUTPUT_SCHEMA.json_schema)
    if errors:
        raise ValueError(f"request goal candidate is invalid: {'; '.join(errors)}")
    return cast(RequestGoalCandidateV1, value)
