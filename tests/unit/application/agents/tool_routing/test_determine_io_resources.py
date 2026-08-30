from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class FakeLLMRuntime:
    outputs: list[object] = field(default_factory=lambda: [_valid_output()])
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate=None,
    ) -> StructuredLLMResult:
        del semantic_validate
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": prompt_input,
                "output_schema": output_schema,
                "trace_context": trace_context,
            }
        )
        return StructuredLLMResult(
            structured_output=self.outputs.pop(0),
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


def _valid_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "input_resource_types": ["TASK"],
        "output_resource_types": ["TASK"],
        "output_effects": ["CREATE"],
        "disposition": "ROUTE_READY",
    }


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
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_routing.determine_io_resources",
        prompt_version="1",
        content_hash="hash",
        agent_role="tool_routing",
        subgraph_name="tool_routing",
        node_name="determine_io_resources",
        node_state="INITIAL",
        purpose="determine_io_resources",
        input_schema_version="v1",
        output_schema_version="v1",
    )
    runtime = FakeLLMRuntime()
    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
    )
    assert candidate.output_pairs[0][0] == "TASK"
    assert candidate.output_pairs[0][1].value == "CREATE"
    assert runtime.calls[0]["prompt_ref"] == prompt_ref
    assert set(runtime.calls[0]["prompt_input"]) == {
        "request_intent",
        "eligible_route_capabilities",
    }


def test_semantic_revision_reuses_base_slot_and_bounded_failure_envelope() -> None:
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
        request_text="create task",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_routing.determine_io_resources",
        prompt_version="1",
        content_hash="hash",
        agent_role="tool_routing",
        subgraph_name="tool_routing",
        node_name="determine_io_resources",
        node_state="INITIAL",
        purpose="determine_io_resources",
        input_schema_version="v1",
        output_schema_version="v1",
    )
    runtime = FakeLLMRuntime(outputs=[{"schema_version": 0}, _valid_output()])

    determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
    )

    assert [call["prompt_ref"] for call in runtime.calls] == [prompt_ref, prompt_ref]
    revision_input = runtime.calls[1]["prompt_input"]
    assert set(revision_input) == {"base_projection", "candidate_output", "failure_record"}
    assert set(revision_input["base_projection"]) == {
        "request_intent",
        "eligible_route_capabilities",
    }
    assert revision_input["failure_record"]["affected_field_paths"] == [
        "$.input_resource_types",
        "$.output_resource_types",
        "$.output_effects",
        "$.disposition",
    ]
