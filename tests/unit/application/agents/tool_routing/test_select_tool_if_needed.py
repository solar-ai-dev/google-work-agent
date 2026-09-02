from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class RecordingLLMRuntime:
    outputs: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        self.calls.append(
            {
                "requested_mode": requested_mode,
                "prompt_ref": prompt_ref,
                "prompt_input": input_projection,
                "output_schema": output_schema_ref,
            }
        )
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=cast(dict[str, object], self.outputs.pop(0)),
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
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
        run_budget=dict(build_default_run_budget()),
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
    budget = build_default_run_budget()
    selected, budget = select_tool_if_needed(
        llm_runtime=RecordingLLMRuntime(outputs=[]),
        route_id="route-1",
        connector_id="google_workspace",
        resource_type="TASK",
        effect="CREATE",
        eligible_tool_ids=("tasks_create_task",),
        request=_request(),
        retry_budget=budget,
    )
    assert selected == "tasks_create_task"
    assert budget == build_default_run_budget()


def test_select_tool__uses_exact__canonical_prompt_projection() -> None:
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


def test_select_semantic__revision_reuses__base_slot() -> None:
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
    revision_input = cast(Mapping[str, object], runtime.calls[1]["prompt_input"])
    assert set(revision_input) == {"base_projection", "candidate_output", "failure_record"}
    assert set(cast(Mapping[str, object], revision_input["base_projection"])) == {
        "route_candidate",
        "registered_candidates",
    }
    failure_record = cast(Mapping[str, object], revision_input["failure_record"])
    assert failure_record["affected_field_paths"] == ["$.selected_tool_id"]
