from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_work_agent.application.workflows.planning_argument_orchestrator import (
    PlanningArgumentOrchestrator,
)
from google_work_agent.application.workflows.planning_argument_writer import (
    PlanningArgumentWriter,
)
from google_work_agent.application.workflows.planning_arguments import DefaultContainerResolver
from google_work_agent.ports import (
    ActualRuntime,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class _Runtime:
    route_ids: list[str] = field(default_factory=list)

    def invoke_structured(self, **kwargs: Any) -> StructuredLLMResult:
        prompt_input = kwargs["prompt_input"]
        route = prompt_input["output_route"]
        route_id = route["route_id"]
        self.route_ids.append(route_id)
        if route["selected_tool_id"] == "tasks_create_task":
            arguments = {"payload": {"title": "Task"}}
        else:
            arguments = {"payload": {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}}
        candidate: dict[str, object] = {
            "schema_version": 1,
            "route_id": route_id,
            "arguments": arguments,
            "evidence_refs": ["ev-1"],
        }
        semantic_validate = kwargs.get("semantic_validate")
        if semantic_validate is not None:
            candidate = semantic_validate(candidate)
        return StructuredLLMResult(
            structured_output=candidate,
            provider="fake",
            model="fake-model",
            requested_mode=RequestedRuntimeMode.API_LLM,
            actual_runtime=ActualRuntime.API_LLM,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            latency_ms=1,
            estimated_cost_usd=0.0,
            fallback_reason=None,
            structured_output_attempts=1,
            provider_request_id=f"provider-{route_id}",
            safe_error_code=None,
        )


def _prompt() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="planning.compose_arguments",
        prompt_version="1",
        content_hash="hash",
        agent_role="planning",
        subgraph_name="planning",
        node_name="compose_arguments",
        node_state="INITIAL",
        purpose="compose_arguments",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="API_LLM",
        request_text="Create a task and draft an email",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def test_orchestrator_invokes_writer_once_per_route_in_frozen_order() -> None:
    runtime = _Runtime()
    orchestrator = PlanningArgumentOrchestrator(
        writer=PlanningArgumentWriter(llm_runtime=runtime, prompt_ref=_prompt()),  # type: ignore[arg-type]
        default_container_resolver=DefaultContainerResolver(
            default_tasklist_id_provider=lambda: "default-list",
        ),
    )
    routes = (
        {
            "route_id": "route-task",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
            "reason_codes": ["USER_REQUEST"],
        },
        {
            "route_id": "route-gmail",
            "resource_type": "GMAIL_DRAFT",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "gmail_create_draft",
            "reason_codes": ["USER_REQUEST"],
        },
    )
    evidence = [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": "resource-1",
            "segment_id": "segment-1",
            "kind": "excerpt",
            "excerpt": "Source",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        }
    ]

    results = orchestrator.compose(
        request=_request(),
        request_intent={  # type: ignore[arg-type]
            "schema_version": 2,
            "meta": {
                "artifact_id": "intent-1",
                "revision": 1,
                "based_on": [],
            },
            "goal": "Create a task and draft an email",
            "completion_conditions": ["A task and an email draft exist."],
            "constraints": [],
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK", "GMAIL_DRAFT"],
            "analysis_requirement": "NONE",
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
        },
        output_routes=routes,  # type: ignore[arg-type]
        evidence_drafts=evidence,  # type: ignore[arg-type]
        analysis_result=None,
    )

    assert runtime.route_ids == ["route-task", "route-gmail"]
    assert [item.candidate["route_id"] for item in results] == [
        "route-task",
        "route-gmail",
    ]
    assert results[0].candidate["arguments"]["task_list_id"] == "default-list"
    assert "task_list_id" not in results[1].candidate["arguments"]
