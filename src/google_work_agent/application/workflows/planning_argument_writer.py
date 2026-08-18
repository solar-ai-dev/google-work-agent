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
    ReviewIssueV1,
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

_ALLOWED_REVISION_SCOPE: Final = ("$.arguments", "$.evidence_refs")


class PlanningArgumentWriter:
    """Invoke Planning argument Prompt variants for exactly one frozen route."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference | None = None,
        revise_prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest = manifest_path or _default_prompt_manifest_path()
        self._prompt_ref = prompt_ref or _load_prompt_reference(
            "planning.compose_arguments",
            manifest,
        )
        self._revise_prompt_ref = revise_prompt_ref or _load_prompt_reference(
            "planning.compose_arguments.revise",
            manifest,
        )

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    @property
    def revise_prompt_ref(self) -> PromptReference:
        return self._revise_prompt_ref

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
            prompt_input=_base_projection(
                request=request,
                request_intent=request_intent,
                bound_tool_schema=bound_tool_schema,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
            ),
            output_schema=TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=_trace_context(
                request=request,
                route_id=bound_tool_schema["route_id"],
                purpose="compose_arguments",
            ),
            semantic_validate=lambda candidate: validate_tool_argument_candidate_v1(
                candidate,
                bound_tool_schema=bound_tool_schema,
                allowed_evidence_refs=allowed_evidence_refs,
            ),
        )

    def revise(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
        candidate_output: ToolArgumentCandidateV1,
        review_issues: list[ReviewIssueV1],
        review_summary: str | None,
    ) -> StructuredLLMResult:
        """Revise one candidate without widening Planning's route authority."""

        allowed_evidence_refs = {draft["evidence_id"] for draft in evidence_drafts}
        base_projection = _base_projection(
            request=request,
            request_intent=request_intent,
            bound_tool_schema=bound_tool_schema,
            evidence_drafts=evidence_drafts,
            analysis_result=analysis_result,
        )
        failure_record = _normalized_failure_record(
            review_issues=review_issues,
            review_summary=review_summary,
        )
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._revise_prompt_ref,
            prompt_input={
                "base_projection": base_projection,
                "candidate_output": dict(candidate_output),
                "failure_record": failure_record,
            },
            output_schema=TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=_trace_context(
                request=request,
                route_id=bound_tool_schema["route_id"],
                purpose="compose_arguments.revise",
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


def _base_projection(
    *,
    request: WorkflowStartRequest,
    request_intent: RequestIntentV2,
    bound_tool_schema: BoundSelectedToolSchemaV1,
    evidence_drafts: list[EvidenceDraftV1],
    analysis_result: WorkAnalysisResultV1 | None,
) -> dict[str, object]:
    return {
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
    }


def _normalized_failure_record(
    *,
    review_issues: list[ReviewIssueV1],
    review_summary: str | None,
) -> dict[str, object]:
    """Project Review issues into the bounded argument-writer revision envelope."""

    reason_codes: list[str] = []
    affected_fields: list[str] = []
    issue_ids: list[str] = []
    for issue in review_issues:
        issue_id = issue.get("issue_id")
        if isinstance(issue_id, str) and issue_id and issue_id not in issue_ids:
            issue_ids.append(issue_id)
        for reason_code in issue.get("reason_codes", []):
            if isinstance(reason_code, str) and reason_code and reason_code not in reason_codes:
                reason_codes.append(reason_code)
        for field_path in issue.get("affected_field_paths", []):
            normalized = _candidate_relative_field_path(field_path)
            if normalized is not None and normalized not in affected_fields:
                affected_fields.append(normalized)

    # Some Review defects are action-scoped but do not nominate a leaf path.
    # In that case the revision remains bounded to the two fields owned by the
    # Argument Writer instead of granting access to tool/effect/id/dependency.
    if not affected_fields:
        affected_fields.extend(_ALLOWED_REVISION_SCOPE)

    return {
        "failure_reason_codes": reason_codes or ["PLAN_REVIEW_REVISE"],
        "affected_fields": affected_fields,
        "allowed_change_scope": list(_ALLOWED_REVISION_SCOPE),
        "review_issue_ids": issue_ids,
        "summary": review_summary,
    }


def _candidate_relative_field_path(field_path: object) -> str | None:
    if not isinstance(field_path, str) or not field_path:
        return None
    for field in ("arguments", "evidence_refs"):
        marker = f".{field}"
        if field_path == field or field_path == f"$.{field}":
            return f"$.{field}"
        if marker in field_path:
            suffix = field_path.split(marker, 1)[1]
            return f"$.{field}{suffix}"
    return None


def _trace_context(
    *, request: WorkflowStartRequest, route_id: str, purpose: str
) -> ObservabilityContext:
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=f"{request.run_id}:planning.{purpose}:{route_id}",
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
