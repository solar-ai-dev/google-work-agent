from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_work_agent.application.orchestration.planning_argument_writer import (
    PlanningArgumentWriter,
)
from google_work_agent.application.orchestration.planning_arguments import DefaultContainerResolver
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class _Runtime:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def invoke_structured(self, **kwargs: Any) -> StructuredLLMResult:
        self.calls.append(kwargs)
        candidate = {
            "schema_version": 1,
            "route_id": kwargs["prompt_input"]["output_route"]["route_id"],
            "arguments": {"payload": {"title": "Prepare report"}},
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
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            latency_ms=1,
            estimated_cost_usd=0.0,
            fallback_reason=None,
            structured_output_attempts=1,
            provider_request_id="req-1",
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
        request_text="Prepare a report task",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _request_intent() -> dict[str, object]:
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "intent-1",
            "revision": 1,
            "based_on": [],
        },
        "goal": "Prepare report task",
        "completion_conditions": ["A task exists with the requested title."],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
    }


def _analysis() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "Task creation is requested.",
        "findings": [],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["ev-1"],
        "resource_refs": [],
        "segment_refs": [],
        "additional_acquisition_request": None,
    }


def _evidence() -> list[dict[str, object]]:
    return [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": "resource-1",
            "segment_id": "segment-1",
            "kind": "excerpt",
            "excerpt": "Prepare report",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        }
    ]


def test_writer_receives_exactly_one_frozen_output_route() -> None:
    runtime = _Runtime()
    writer = PlanningArgumentWriter(llm_runtime=runtime, prompt_ref=_prompt())  # type: ignore[arg-type]
    route = {
        "route_id": "route-task-create",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": ["USER_REQUEST"],
    }
    resolver = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "task-list-default",
    )
    bound = resolver.bind_selected_tool_schema(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
    )

    result = writer.invoke(
        request=_request(),
        request_intent=_request_intent(),  # type: ignore[arg-type]
        bound_tool_schema=bound,
        evidence_drafts=_evidence(),  # type: ignore[arg-type]
        analysis_result=_analysis(),  # type: ignore[arg-type]
    )

    prompt_input = runtime.calls[0]["prompt_input"]
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "output_route",
        "selected_tool_schema",
        "work_analysis",
        "evidence",
    }
    assert prompt_input["output_route"] == {
        "route_id": "route-task-create",
        "connector_id": "google_workspace",
        "resource_type": "TASK",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
    }
    assert "output_routes" not in prompt_input
    assert result.structured_output["arguments"]["task_list_id"] == "task-list-default"  # type: ignore[index]


def test_writer_projects_only_bounded_evidence_fields() -> None:
    runtime = _Runtime()
    writer = PlanningArgumentWriter(llm_runtime=runtime, prompt_ref=_prompt())  # type: ignore[arg-type]
    route = {
        "route_id": "route-task-create",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": ["USER_REQUEST"],
    }
    bound = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "task-list-default",
    ).bind_selected_tool_schema(
        route=route,  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
    )

    writer.invoke(
        request=_request(),
        request_intent=_request_intent(),  # type: ignore[arg-type]
        bound_tool_schema=bound,
        evidence_drafts=_evidence(),  # type: ignore[arg-type]
        analysis_result=None,
    )

    assert runtime.calls[0]["prompt_input"]["evidence"] == [
        {
            "evidence_ref": "ev-1",
            "excerpt": "Prepare report",
            "role": "SUPPORTS",
            "resource_ref": "resource-1",
        }
    ]
