from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import pytest

from google_work_agent.ports.observability_events import ObservabilityContext
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    PlanningArgumentOrchestrator,
)
from google_work_agent.application.orchestration.planning_argument_writer import PlanningArgumentWriter
from google_work_agent.application.orchestration.planning_arguments import (
    DefaultContainerResolver,
    PlanningArgumentBindingError,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    assemble_action_plan_draft_v1_compat,
    derive_action_dependencies_deterministically,
    materialize_action_seeds,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)
from google_work_agent.application.orchestration.tool_routing import OutputToolRouteV1
from google_work_agent.ports import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
                "output_schema": output_schema,
                "trace_context": trace_context,
                "semantic_validate": semantic_validate,
            }
        )
        return self.queued.popleft()


def test_candidate_must_satisfy_bound_selected_tool_schema() -> None:
    route = _task_create_route()
    bound = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "list-default"
    ).bind_selected_tool_schema(
        route=route,
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
    )

    with pytest.raises(PlanningArgumentBindingError, match="payload.title is required"):
        validate_tool_argument_candidate_v1(
            {
                "schema_version": 1,
                "route_id": route["route_id"],
                "arguments": {"payload": {}},
                "evidence_refs": ["ev-1"],
            },
            bound_tool_schema=bound,
            allowed_evidence_refs={"ev-1"},
        )


def test_initial_argument_writer_sees_exactly_one_frozen_route() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "route_id": "route-task-create",
                "arguments": {"payload": {"title": "Prepare report"}},
                "evidence_refs": ["ev-1"],
            }
        )
    )
    writer = _writer(runtime)
    orchestrator = PlanningArgumentOrchestrator(
        writer=writer,
        default_container_resolver=DefaultContainerResolver(
            default_tasklist_id_provider=lambda: "list-default"
        ),
    )

    results = orchestrator.compose(
        request=_request(),
        request_intent=_intent(),
        output_routes=(_task_create_route(),),
        evidence_drafts=_evidence(),
        analysis_result=_analysis(),
    )

    prompt_input = runtime.calls[0]["prompt_input"]
    assert isinstance(prompt_input, dict)
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
    assert results[0].candidate["arguments"]["task_list_id"] == "list-default"


def test_argument_revision_uses_only_revision_envelope() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "route_id": "route-task-create",
                "arguments": {
                    "task_list_id": "list-default",
                    "payload": {"title": "Prepare final report"},
                },
                "evidence_refs": ["ev-1"],
            }
        )
    )
    writer = _writer(runtime)
    bound = DefaultContainerResolver(
        default_tasklist_id_provider=lambda: "list-default"
    ).bind_selected_tool_schema(
        route=_task_create_route(),
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
    )

    writer.revise(
        request=_request(),
        request_intent=_intent(),
        bound_tool_schema=bound,
        evidence_drafts=_evidence(),
        analysis_result=_analysis(),
        candidate_output={
            "schema_version": 1,
            "route_id": "route-task-create",
            "arguments": {
                "task_list_id": "list-default",
                "payload": {"title": "Prepare report"},
            },
            "evidence_refs": ["ev-1"],
        },
        review_issues=[
            {
                "schema_version": 2,
                "issue_id": "issue-1",
                "kind": "ARGUMENT_MISMATCH",
                "message": "Title must reflect final report.",
                "affected_action_ids": ["action-1"],
                "affected_field_paths": ["$.actions[0].arguments.payload.title"],
                "evidence_refs": ["ev-1"],
                "resource_refs": ["gmail_thread:thread-1"],
                "reason_codes": ["ARGUMENT_MISMATCH"],
            }
        ],
        review_summary="Revise the task title.",
    )

    prompt_input = runtime.calls[0]["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert set(prompt_input) == {"base_projection", "candidate_output", "failure_record"}
    failure_record = prompt_input["failure_record"]
    assert isinstance(failure_record, dict)
    assert failure_record["affected_field_paths"] == ["$.arguments.payload.title"]
    assert set(failure_record) == {
        "schema_version",
        "failure_id",
        "failure_reason_code",
        "failure_origin",
        "detected_by",
        "runtime_disposition",
        "experiment_disposition",
        "affected_field_paths",
        "evidence_refs",
    }


def test_compat_plan_copies_route_authority_and_builds_expected_deterministically() -> None:
    ids = iter(("plan-1", "action-1"))
    result = assemble_action_plan_draft_v1_compat(
        request_intent=_intent(),
        analysis_result=_analysis(),
        evidence_drafts=_evidence(),
        output_routes=(_task_create_route(),),
        argument_candidates=(
            {
                "schema_version": 1,
                "route_id": "route-task-create",
                "arguments": {
                    "task_list_id": "list-default",
                    "payload": {
                        "title": "Prepare report",
                        "scheduled_date": "2026-08-20",
                    },
                },
                "evidence_refs": ["ev-1"],
            },
        ),
        plan_id_factory=lambda: next(ids),
        action_id_factory=lambda: next(ids),
    )

    action = result["actions"][0]
    assert action["tool_name"] == "tasks_create_task"
    assert action["effect"] == "CREATE"
    assert action["action_id"] == "action-1"
    assert action["expected"] == {
        "payload": {"title": "Prepare report", "due": "2026-08-20"}
    }
    assert action["depends_on_action_ids"] == []


def test_same_resource_dependency_is_code_derived_and_revision_preserves_action_ids() -> None:
    routes: tuple[OutputToolRouteV1, ...] = (
        {
            "route_id": "route-update",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "effect": "UPDATE",
            "selected_tool_id": "calendar_update_event",
            "reason_codes": ["USER_REQUEST"],
        },
        {
            "route_id": "route-delete",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "effect": "DELETE",
            "selected_tool_id": "calendar_delete_event",
            "reason_codes": ["USER_REQUEST"],
        },
    )
    candidates = (
        {
            "schema_version": 1,
            "route_id": "route-update",
            "arguments": {
                "calendar_id": "cal-1",
                "event_id": "event-1",
                "payload": {"title": "Updated"},
            },
            "evidence_refs": ["ev-1"],
        },
        {
            "schema_version": 1,
            "route_id": "route-delete",
            "arguments": {"calendar_id": "cal-1", "event_id": "event-1"},
            "evidence_refs": ["ev-1"],
        },
    )
    action_ids = iter(("action-update", "action-delete"))
    seeds = materialize_action_seeds(
        output_routes=routes,
        argument_candidates=candidates,  # type: ignore[arg-type]
        action_id_factory=lambda: next(action_ids),
    )
    dependencies = derive_action_dependencies_deterministically(seeds)

    assert dependencies == (
        {
            "action_id": "action-delete",
            "depends_on_action_id": "action-update",
            "reason": "SAME_RESOURCE_ORDER",
        },
    )


def _writer(runtime: FakeLLMRuntime) -> PlanningArgumentWriter:
    return PlanningArgumentWriter(
        llm_runtime=runtime,  # type: ignore[arg-type]
        prompt_ref=_prompt_ref("planning.compose_arguments", "INITIAL", "compose_arguments"),
        revise_prompt_ref=_prompt_ref(
            "planning.compose_arguments.revise", "SEMANTIC_REVISION", "revise"
        ),
    )


def _prompt_ref(prompt_id: str, node_state: str, purpose: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test-bundle",
        prompt_id=prompt_id,
        prompt_version="test",
        content_hash="hash",
        agent_role="planning",
        subgraph_name="planning",
        node_name="compose_arguments",
        node_state=node_state,
        purpose=purpose,
        input_schema_version="test-input",
        output_schema_version="test-output",
    )


def _llm_result(output: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=output,
        provider="fake",
        model="fake",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1,
        estimated_cost_usd=0.0,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="provider-1",
        safe_error_code=None,
        provider_calls_consumed=1,
    )


def _task_create_route() -> OutputToolRouteV1:
    return {
        "route_id": "route-task-create",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": ["USER_REQUEST"],
    }


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="보고서 준비 Task를 만들어줘",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "보고서 준비 Task 생성",
        "completion_conditions": ["Task 생성 계획을 만든다."],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
    }


def _evidence() -> list[EvidenceDraftV1]:
    return [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": "gmail_thread:thread-1",
            "segment_id": "seg-1",
            "kind": "excerpt",
            "excerpt": "보고서를 준비해 주세요.",
            "locator": {"kind": "resource_payload"},
            "reason_codes": ["SUPPORTS"],
        }
    ]


def _analysis() -> WorkAnalysisResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "보고서 준비 업무가 확인됨",
        "findings": [],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["ev-1"],
        "resource_refs": [
            {
                "resource_handle": "gmail_thread:thread-1",
                "source": "GMAIL",
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "parent_id": None,
                "version": "1",
            }
        ],
        "segment_refs": [],
        "additional_acquisition_request": None,
    }
