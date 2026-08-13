"""Tests for the Tool Route semantic LLM stage (ToolRouteAgent) and its wiring
into ToolRouteCoordinator.route(). Registry binding, PolicyPreconditionResolver,
and freeze stay deterministic; these tests prove the LLM only supplies a
semantic candidate / tool selection, and that Registry authority still wins."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import pytest
from tests.support.prompt_manifests import write_runtime_active_manifest

from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.handoff_contracts import RequestIntentV1
from google_work_agent.application.workflows.tool_route_semantic import (
    ToolRouteAgent,
    load_tool_route_determine_io_resources_prompt_reference,
    load_tool_route_select_tool_if_needed_prompt_reference,
)
from google_work_agent.application.workflows.tool_routing import (
    ToolRouteCoordinator,
    ToolRouteValidationError,
    output_routes,
)
from google_work_agent.domain import (
    ConnectorToolCatalog,
    SignedToolRegistry,
    build_p0_tool_registry,
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
                "prompt_id": prompt_ref.prompt_id,
                "prompt_input": dict(prompt_input),
                "output_schema": output_schema,
            }
        )
        result = self.queued.popleft()
        if semantic_validate is not None:
            semantic_validate(result.structured_output)
        return result


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
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


def _catalog() -> ConnectorToolCatalog:
    catalog = ConnectorToolCatalog()
    catalog.register(connector_id="google_workspace", registry=build_p0_tool_registry())
    return catalog


def _catalog_with_duplicate_task_create() -> ConnectorToolCatalog:
    base = build_p0_tool_registry()
    entries = list(base.list_entries())
    original = next(entry for entry in entries if entry.tool_name == "tasks_create_task")
    duplicate = replace(original, tool_name="tasks_create_task_v2")
    catalog = ConnectorToolCatalog()
    catalog.register(
        connector_id="google_workspace",
        registry=SignedToolRegistry((*entries, duplicate)),
    )
    return catalog


def _intent() -> RequestIntentV1:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": {"summary": "goal", "user_visible_objective": "goal"},
        "completion_criteria": ["done"],
        "semantic_constraints": {
            "topics": [],
            "people": [],
            "time": [],
            "sources": [],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {"is_unsupported": False, "reason_code": None, "explanation": None},
        "response_disposition": "ACTION_REQUIRED",
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "REQUIRED",
    }


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Create a task to follow up with Kim.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )


def _agent(
    runtime: FakeLLMRuntime, *, tool_catalog: ConnectorToolCatalog | None = None
) -> ToolRouteAgent:
    return ToolRouteAgent(
        llm_runtime=runtime,
        tool_catalog=tool_catalog or _catalog(),
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="tool_route.determine_io_resources",
            prompt_version="0.9.0",
            content_hash="hash",
            agent_role="tool_route",
            subgraph_name="tool_route",
            node_name="determine_io_resources",
            node_state="INITIAL",
            purpose="determine_io_resources",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
        select_tool_prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="tool_route.select_tool_if_needed",
            prompt_version="0.9.0",
            content_hash="hash",
            agent_role="tool_route",
            subgraph_name="tool_route",
            node_name="select_tool_if_needed",
            node_state="INITIAL",
            purpose="select_tool_if_needed",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )


def test_determine_io_resources_and_select_tool_if_needed_prompt_refs_resolve(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path,
        prompt_ids={"tool_route.determine_io_resources", "tool_route.select_tool_if_needed"},
    )

    determine_ref = load_tool_route_determine_io_resources_prompt_reference(manifest_path)
    select_ref = load_tool_route_select_tool_if_needed_prompt_reference(manifest_path)

    assert determine_ref.prompt_id == "tool_route.determine_io_resources"
    assert determine_ref.agent_role == "tool_route"
    assert select_ref.prompt_id == "tool_route.select_tool_if_needed"
    assert select_ref.agent_role == "tool_route"


def test_semantic_candidate_from_llm_drives_task_create_with_deterministic_policy_read() -> None:
    """LLM candidate: TASK CREATE. Deterministic final plan must still add
    the TASK/TASK_LIST duplicate-check reads -- the LLM never produced those,
    proving PolicyPreconditionResolver (not the LLM) owns them."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": ["TASK"],
                "output_effects": ["CREATE"],
                "disposition": "ROUTE_READY",
            }
        )
    )
    agent = _agent(runtime)
    request_intent = _intent()
    request = _request()

    candidate = agent.determine_semantic_candidate(request_intent=request_intent, request=request)

    assert runtime.calls[0]["prompt_id"] == "tool_route.determine_io_resources"
    prompt_input = cast("dict[str, object]", runtime.calls[0]["prompt_input"])
    assert "gold" not in prompt_input
    assert candidate.output_mode == "ACTION"
    assert candidate.output_pairs[0][0] == "TASK"

    sequence = iter(f"route-{index}" for index in range(30))
    coordinator = ToolRouteCoordinator(tool_catalog=_catalog(), id_factory=lambda: next(sequence))
    result = coordinator.route(request_intent=request_intent, semantic_candidate=candidate)

    assert result["disposition"] == "ROUTE_READY"
    plan = result["tool_route_plan"]
    assert plan is not None
    assert output_routes(plan)[0]["selected_tool_id"] == "tasks_create_task"
    resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
    assert resources == {"TASK", "TASK_LIST"}


def test_semantic_candidate_from_llm_drives_calendar_create_with_deterministic_conflict_reads() -> (
    None
):
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": ["CALENDAR"],
                "output_effects": ["CREATE"],
                "disposition": "ROUTE_READY",
            }
        )
    )
    agent = _agent(runtime)
    request_intent = _intent()
    candidate = agent.determine_semantic_candidate(
        request_intent=request_intent, request=_request()
    )

    sequence = iter(f"route-{index}" for index in range(30))
    coordinator = ToolRouteCoordinator(tool_catalog=_catalog(), id_factory=lambda: next(sequence))
    result = coordinator.route(request_intent=request_intent, semantic_candidate=candidate)

    plan = result["tool_route_plan"]
    assert plan is not None
    resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
    assert resources == {"CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"}
    assert output_routes(plan)[0]["selected_tool_id"] == "calendar_create_event"


def test_semantic_candidate_is_used_instead_of_deterministic_fallback() -> None:
    """request_intent carries no resource/effect hints at all -- the
    deterministic fallback (determine_semantic_routes) would reject this
    ACTION request outright. Passing semantic_candidate must still succeed,
    proving the LLM candidate is the one owner in this call, not a second
    opinion layered on top of the deterministic parser."""
    request_intent = _intent()
    assert request_intent["requested_resource_hints"] == []
    assert request_intent["requested_effect_hints"] == []

    sequence = iter(f"route-{index}" for index in range(30))
    coordinator = ToolRouteCoordinator(tool_catalog=_catalog(), id_factory=lambda: next(sequence))
    from google_work_agent.application.workflows.tool_routing import SemanticRouteCandidate
    from google_work_agent.domain import EffectType

    candidate = SemanticRouteCandidate(
        input_resource_types=(),
        output_pairs=(("TASK", EffectType.CREATE),),
        output_mode="ACTION",
        analysis_requirement="NONE",
    )

    result = coordinator.route(request_intent=request_intent, semantic_candidate=candidate)

    assert result["disposition"] == "ROUTE_READY"


def test_select_tool_if_needed_invoked_when_registry_has_multiple_candidates() -> None:
    catalog = _catalog_with_duplicate_task_create()
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": ["TASK"],
                "output_effects": ["CREATE"],
                "disposition": "ROUTE_READY",
            }
        )
    )
    runtime.queued.append(
        _llm_result(
            {"schema_version": 1, "route_id": "route-0", "selected_tool_id": "tasks_create_task_v2"}
        )
    )
    agent = _agent(runtime, tool_catalog=catalog)
    request_intent = _intent()
    request = _request()
    candidate = agent.determine_semantic_candidate(request_intent=request_intent, request=request)

    sequence = iter(f"route-{index}" for index in range(30))
    coordinator = ToolRouteCoordinator(tool_catalog=catalog, id_factory=lambda: next(sequence))
    result = coordinator.route(
        request_intent=request_intent,
        semantic_candidate=candidate,
        select_tool=lambda **kwargs: agent.select_tool_if_needed(request=request, **kwargs),
    )

    assert result["disposition"] == "ROUTE_READY"
    plan = result["tool_route_plan"]
    assert plan is not None
    selected = output_routes(plan)[0]
    assert selected["selected_tool_id"] == "tasks_create_task_v2"
    assert selected["reason_codes"] == ["LLM_SELECTED_FROM_REGISTRY_CANDIDATES"]
    assert runtime.calls[1]["prompt_id"] == "tool_route.select_tool_if_needed"
    select_prompt_input = cast("dict[str, object]", runtime.calls[1]["prompt_input"])
    assert set(cast("list[str]", select_prompt_input["eligible_tool_ids"])) == {
        "tasks_create_task",
        "tasks_create_task_v2",
    }


def test_select_tool_if_needed_rejects_a_tool_outside_the_registry_candidates() -> None:
    """Registry authority wins: if the LLM returns a tool_name that was not
    among eligible_tool_ids, the route must fail closed -- it can never
    reach a final ToolRoutePlanV2."""
    catalog = _catalog_with_duplicate_task_create()
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": ["TASK"],
                "output_effects": ["CREATE"],
                "disposition": "ROUTE_READY",
            }
        )
    )
    runtime.queued.append(
        _llm_result(
            {"schema_version": 1, "route_id": "route-0", "selected_tool_id": "gmail_send"}
        )
    )
    agent = _agent(runtime, tool_catalog=catalog)
    request_intent = _intent()
    request = _request()
    candidate = agent.determine_semantic_candidate(request_intent=request_intent, request=request)

    sequence = iter(f"route-{index}" for index in range(30))
    coordinator = ToolRouteCoordinator(tool_catalog=catalog, id_factory=lambda: next(sequence))

    result = coordinator.route(
        request_intent=request_intent,
        semantic_candidate=candidate,
        select_tool=lambda **kwargs: agent.select_tool_if_needed(request=request, **kwargs),
    )

    assert result["disposition"] == "BLOCKED"
    assert result["tool_route_plan"] is None
    assert any("Registry-eligible" in code for code in result["reason_codes"])


def test_determine_semantic_candidate_rejects_needs_confirmation_disposition() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "NEEDS_CONFIRMATION",
            }
        )
    )
    agent = _agent(runtime)

    with pytest.raises(ToolRouteValidationError, match="not ready"):
        agent.determine_semantic_candidate(request_intent=_intent(), request=_request())
