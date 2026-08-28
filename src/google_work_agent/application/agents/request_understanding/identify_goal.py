from __future__ import annotations

from pathlib import Path

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentCandidateV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.orchestration.contracts import ConfirmationResponseProjectionV1
from google_work_agent.application.orchestration.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

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
            "schema_version": {"type": "integer", "enum": [2]},
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


def identify_goal(
    *,
    llm_runtime: StructuredLLMRuntime,
    request: WorkflowStartRequest,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> RequestIntentCandidateV1:
    """Invoke the existing broad classify PromptRef once; atomic placement does not add LLM calls."""
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.classify", manifest_path or default_prompt_manifest_path()
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "entry_mode": request.entry_mode,
        "language": None,
        "selected_resources": list(request.selected_resource_ids),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    result = llm_runtime.invoke_structured(
        prompt_ref=resolved_prompt_ref,
        prompt_input=prompt_input,
        output_schema=REQUEST_INTENT_OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:request_understanding.classify",
        ),
        semantic_validate=validate_intent,
    )
    return validate_intent(result.structured_output)  # type: ignore[return-value]
