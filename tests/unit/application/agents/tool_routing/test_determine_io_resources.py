from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.orchestration.contracts import build_default_run_budget
from google_work_agent.application.tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.observability_events import ObservabilityContext


@dataclass
class FakeLLMRuntime:
    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate=None,
    ) -> StructuredLLMResult:
        return StructuredLLMResult(
            structured_output={
                "schema_version": 1,
                "input_resource_types": ["TASK"],
                "output_resource_types": ["TASK"],
                "output_effects": ["CREATE"],
                "disposition": "ROUTE_READY",
            },
            provider="fake",
            model="fake",
            requested_mode=RequestedRuntimeMode.AUTO,
            actual_runtime=ActualRuntime.API_LLM,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            latency_ms=1,
            estimated_cost_usd=None,
            fallback_reason=None,
            structured_output_attempts=1,
            provider_request_id="provider-request-1",
            safe_error_code=None,
        )


def test_task_create_produces_semantic_candidate_without_tool_identity() -> None:
    catalog = load_signed_tool_registry()
    intent = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create task",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="태스크 만들어줘",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_route.determine_io_resources",
        prompt_version="1",
        content_hash="hash",
        agent_role="tool_route",
        subgraph_name="tool_route",
        node_name="determine_io_resources",
        node_state="INITIAL",
        purpose="determine_io_resources",
        input_schema_version="v1",
        output_schema_version="v1",
    )
    revision_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_route.determine_io_resources.revise",
        prompt_version="1",
        content_hash="hash-r",
        agent_role="tool_route",
        subgraph_name="tool_route",
        node_name="determine_io_resources",
        node_state="SEMANTIC_REVISION",
        purpose="determine_io_resources",
        input_schema_version="v1",
        output_schema_version="v1",
    )
    candidate, _ = determine_io_resources(
        llm_runtime=FakeLLMRuntime(),
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
        revision_prompt_ref=revision_ref,
    )
    assert candidate.output_pairs[0][0] == "TASK"
    assert candidate.output_pairs[0][1].value == "CREATE"
