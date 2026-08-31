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
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

DETECT_AMBIGUITY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="request-ambiguity-v1",
    json_schema={
        "type": "object",
        "required": ["requires_confirmation", "reason_codes", "missing_fields"],
        "additionalProperties": False,
        "properties": {
            "requires_confirmation": {"type": "boolean"},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
        },
    },
)


def detect_ambiguity(
    *,
    llm_runtime: StructuredLLMRuntime,
    request: WorkflowStartRequest,
    goal_candidate: RequestGoalCandidateV1,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> AmbiguityV1:
    """Decide only current-Run, user-owned ambiguity."""
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "request_understanding.detect_ambiguity",
        manifest_path or default_prompt_manifest_path(),
    )
    prompt_input: dict[str, object] = {
        "user_request": request.request_text,
        "goal_candidate": dict(goal_candidate),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    result = llm_runtime.invoke_structured(
        prompt_ref=resolved_prompt_ref,
        prompt_input=prompt_input,
        output_schema=DETECT_AMBIGUITY_OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:request.detect_ambiguity",
        ),
        semantic_validate=_validate_ambiguity,
    )
    return _validate_ambiguity(result.structured_output)


def _validate_ambiguity(value: object) -> AmbiguityV1:
    if not isinstance(value, dict) or set(value) != {
        "requires_confirmation",
        "reason_codes",
        "missing_fields",
    }:
        raise ValueError("request ambiguity fields are invalid")
    requires_confirmation = value.get("requires_confirmation")
    reason_codes = value.get("reason_codes")
    missing_fields = value.get("missing_fields")
    if not isinstance(requires_confirmation, bool):
        raise ValueError("requires_confirmation must be boolean")
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must contain strings")
    if not isinstance(missing_fields, list) or any(
        not isinstance(item, str) for item in missing_fields
    ):
        raise ValueError("missing_fields must contain strings")
    if requires_confirmation and not reason_codes:
        raise ValueError("reason_codes are required when confirmation is required")
    return {
        "requires_confirmation": requires_confirmation,
        "reason_codes": reason_codes,
        "missing_fields": missing_fields,
    }
