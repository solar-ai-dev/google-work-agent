from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.application.orchestration.contracts import build_default_run_budget
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class RecordingLLMRuntime:
    outputs: list[object]
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


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="create task",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="tool_routing.select_tool_if_needed",
        prompt_version="1",
        content_hash="hash",
        agent_role="tool_routing",
        subgraph_name="tool_routing",
        node_name="select_tool_if_needed",
        node_state="INITIAL",
        purpose="select_tool_if_needed",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def test_select_tool_if_needed__single_registry_candidate__does_not_require_llm() -> None:
    selected, budget = select_tool_if_needed(
        llm_runtime=None,
        route_id="route-1",
        connector_id="google_workspace",
        resource_type="TASK",
        effect="CREATE",
        eligible_tool_ids=("tasks_create_task",),
        request=None,
        retry_budget={},
    )  # type: ignore[arg-type]
    assert selected == "tasks_create_task"
    assert budget == {}


def test_select_tool_uses_exact_canonical_prompt_projection() -> None:
    runtime = RecordingLLMRuntime(
        outputs=[
            {
                "schema_version": 1,
                "route_id": "route-1",
                "selected_tool_id": "tasks_create_task",
            }
        ]
    )

    selected, _ = select_tool_if_needed(
        llm_runtime=runtime,
        route_id="route-1",
        connector_id="google_workspace",
        resource_type="TASK",
        effect="CREATE",
        eligible_tool_ids=("tasks_create_task", "tasks_create_task_v2"),
        request=_request(),
        retry_budget=build_default_run_budget(),
        prompt_ref=_prompt_ref(),
    )

    assert selected == "tasks_create_task"
    assert runtime.calls[0]["prompt_ref"] == _prompt_ref()
    assert runtime.calls[0]["prompt_input"] == {
        "route_candidate": {
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "TASK",
            "effect": "CREATE",
        },
        "registered_candidates": [
            {"tool_id": "tasks_create_task"},
            {"tool_id": "tasks_create_task_v2"},
        ],
    }


def test_select_semantic_revision_reuses_base_slot() -> None:
    runtime = RecordingLLMRuntime(
        outputs=[
            {
                "schema_version": 1,
                "route_id": "route-1",
                "selected_tool_id": "invented_tool",
            },
            {
                "schema_version": 1,
                "route_id": "route-1",
                "selected_tool_id": "tasks_create_task",
            },
        ]
    )

    select_tool_if_needed(
        llm_runtime=runtime,
        route_id="route-1",
        connector_id="google_workspace",
        resource_type="TASK",
        effect="CREATE",
        eligible_tool_ids=("tasks_create_task", "tasks_create_task_v2"),
        request=_request(),
        retry_budget=build_default_run_budget(),
        prompt_ref=_prompt_ref(),
    )

    assert [call["prompt_ref"] for call in runtime.calls] == [_prompt_ref(), _prompt_ref()]
    revision_input = runtime.calls[1]["prompt_input"]
    assert set(revision_input) == {"base_projection", "candidate_output", "failure_record"}
    assert set(revision_input["base_projection"]) == {
        "route_candidate",
        "registered_candidates",
    }
    assert revision_input["failure_record"]["affected_field_paths"] == ["$.selected_tool_id"]
