"""Per-output-route Planning argument writer.

The writer owns exactly one LLM responsibility: produce business arguments for
one already-selected output Tool.  It never sees sibling output routes and it
never chooses a Tool.  Container/default binding is performed before the call
by :mod:`planning_arguments` and revalidated after the call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.planning_arguments import (
    BoundSelectedToolSchemaV1,
    ToolArgumentCandidateV1,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_prompt_reference,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
    WorkflowStartRequest,
)

TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA: Final = OutputSchemaDefinition(
    schema_version="tool-argument-candidate-v1",
    json_schema={
        "type": "object",
        "required": ["schema_version", "route_id", "arguments", "evidence_refs"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "route_id": {"type": "string", "minLength": 1},
            "arguments": {"type": "object"},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
        },
    },
)


class PlanningArgumentWriter:
    """Invoke ``planning.compose_arguments`` for exactly one frozen route."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref or _load_prompt_reference(
            "planning.compose_arguments",
            manifest_path or _default_prompt_manifest_path(),
        )

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    def invoke(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
    ) -> StructuredLLMResult:
        allowed_evidence_refs = {draft["evidence_id"] for draft in evidence_drafts}
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "output_route": {
                    "route_id": bound_tool_schema["route_id"],
                    "connector_id": bound_tool_schema["connector_id"],
                    "resource_type": bound_tool_schema["resource_type"],
                    "effect": bound_tool_schema["effect"],
                    "selected_tool_id": bound_tool_schema["selected_tool_id"],
                },
                "selected_tool_schema": bound_tool_schema["argument_schema"],
                "work_analysis": analysis_result,
                "evidence": _planning_evidence_projection(evidence_drafts),
            },
            output_schema=TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=(
                    f"{request.run_id}:planning.compose_arguments:"
                    f"{bound_tool_schema['route_id']}"
                ),
            ),
            semantic_validate=lambda candidate: validate_tool_argument_candidate_v1(
                candidate,
                bound_tool_schema=bound_tool_schema,
                allowed_evidence_refs=allowed_evidence_refs,
            ),
        )

    @staticmethod
    def validated_candidate(
        llm_result: StructuredLLMResult,
        *,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> ToolArgumentCandidateV1:
        return validate_tool_argument_candidate_v1(
            llm_result.structured_output,
            bound_tool_schema=bound_tool_schema,
            allowed_evidence_refs={draft["evidence_id"] for draft in evidence_drafts},
        )


def _planning_evidence_projection(
    evidence_drafts: list[EvidenceDraftV1],
) -> list[dict[str, object]]:
    """Project run-scoped Evidence into the bounded Planning prompt contract."""

    result: list[dict[str, object]] = []
    for draft in evidence_drafts:
        role = next(
            (
                code
                for code in draft["reason_codes"]
                if code in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}
            ),
            "CONTEXT",
        )
        result.append(
            {
                "evidence_ref": draft["evidence_id"],
                "excerpt": draft["excerpt"],
                "role": role,
                "resource_ref": draft["resource_handle"],
            }
        )
    return result


__all__ = [
    "PlanningArgumentWriter",
    "TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA",
]
