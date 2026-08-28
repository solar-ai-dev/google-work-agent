from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.orchestration.contracts import (
    BudgetDecision,
    RunBudgetV1,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.orchestration.failure_record import build_failure_record_v1
from google_work_agent.application.orchestration.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    legacy_post_call_projection,
    provider_dispatch_budget_scope,
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

TOOL_SELECTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="tool-selection-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "route_id", "selected_tool_id"],
        "properties": {
            "schema_version": {"const": 1},
            "route_id": {"type": "string"},
            "selected_tool_id": {"type": "string"},
        },
    },
)


def select_tool_if_needed(
    *,
    llm_runtime: StructuredLLMRuntime,
    route_id: str,
    connector_id: str,
    resource_type: str,
    effect: str,
    eligible_tool_ids: tuple[str, ...],
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV1,
    prompt_ref: PromptReference | None = None,
    revision_prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
) -> tuple[str, RunBudgetV1]:
    if len(eligible_tool_ids) == 1:
        return eligible_tool_ids[0], retry_budget
    if not eligible_tool_ids:
        raise ToolRouteValidationError("tool selection requires Registry-eligible candidates")
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "tool_route.select_tool_if_needed", manifest_path or default_prompt_manifest_path()
    )
    resolved_revision_ref = revision_prompt_ref or load_prompt_reference(
        "tool_route.select_tool_if_needed.revise", manifest_path or default_prompt_manifest_path()
    )
    base_projection = {
        "route_id": route_id,
        "connector_id": connector_id,
        "resource_type": resource_type,
        "effect": effect,
        "eligible_tool_ids": list(eligible_tool_ids),
    }
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.invoke_structured(
            prompt_ref=resolved_prompt_ref,
            prompt_input=base_projection,
            output_schema=TOOL_SELECTION_OUTPUT_SCHEMA,
            trace_context=_trace(request, "tool_route.select_tool_if_needed"),
        )
        selected = _validated_selection(
            result.structured_output, eligible_tool_ids=eligible_tool_ids
        )
        if selected is not None:
            return selected, legacy_post_call_projection(retry_budget)
        failure_code = "TOOL_SELECTION_INVALID"
        signature = build_semantic_failure_signature_v1(
            node_id="tool_route.select_tool_if_needed", failure_reason_codes=[failure_code]
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            raise ToolRouteValidationError(
                "tool selection revision denied: same failure signature already used"
            )
        revised = llm_runtime.invoke_structured(
            prompt_ref=resolved_revision_ref,
            prompt_input={
                "base_projection": dict(base_projection),
                "candidate_output": result.structured_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code=failure_code,
                    failure_origin="LLM_OUTPUT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=["$.selected_tool_id"],
                    failure_context_ids=["selected_tool_id is not a Registry-eligible candidate"],
                ),
            },
            output_schema=TOOL_SELECTION_OUTPUT_SCHEMA,
            trace_context=_trace(request, "tool_route.select_tool_if_needed.semantic_revision"),
        )
        selected = _validated_selection(
            revised.structured_output, eligible_tool_ids=eligible_tool_ids
        )
        if selected is None:
            raise ToolRouteValidationError(
                "selected tool is not a Registry-eligible candidate after revision"
            )
        return selected, legacy_post_call_projection(decision["run_budget"])


def _validated_selection(value: object, *, eligible_tool_ids: tuple[str, ...]) -> str | None:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return None
    if not isinstance(value.get("route_id"), str) or not value.get("route_id"):
        return None
    selected = value.get("selected_tool_id")
    return selected if isinstance(selected, str) and selected in eligible_tool_ids else None


def _trace(request: WorkflowStartRequest, node_id: str) -> ObservabilityContext:
    return ObservabilityContext(
        request_id=request.correlation.request_id,
        command_id=request.correlation.command_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
        langgraph_thread_id=request.workflow_key,
        llm_call_id=f"{request.run_id}:{node_id}",
    )
