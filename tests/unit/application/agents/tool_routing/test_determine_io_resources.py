from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _valid_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "input_resource_types": ["TASK"],
        "output_resource_types": ["TASK"],
        "output_effects": ["CREATE"],
        "disposition": "ROUTE_READY",
    }


def test_task_create__produces_semantic_candidate__without_tool_identity() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
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
        run_budget=dict(build_default_run_budget()),
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
    runtime = FakeStructuredInferencePort(outputs=[])
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
    assert runtime.calls == []


def test_calendar_create__uses_exact_validated_intent__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-calendar", "revision": 1, "based_on": []},
        "goal": "create calendar event",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-calendar",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="create an event",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == (("CALENDAR_EVENT", EffectType.CREATE),)
    assert candidate.output_mode == "ACTION"


def test_semantic_revision_reuses__base_slot_and__bounded_failure_envelope() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create task",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK", "CALENDAR_EVENT"],
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
        run_budget=dict(build_default_run_budget()),
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
    runtime = FakeStructuredInferencePort(outputs=[{"schema_version": 0}, _valid_output()])

    determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=prompt_ref,
    )

    assert [call["prompt_ref"] for call in runtime.calls] == [prompt_ref, prompt_ref]
    revision_input = cast(Mapping[str, object], runtime.calls[1]["prompt_input"])
    assert set(revision_input) == {"base_projection", "candidate_output", "failure_record"}
    assert set(cast(Mapping[str, object], revision_input["base_projection"])) == {
        "request_intent",
        "eligible_route_capabilities",
    }
    failure_record = cast(Mapping[str, object], revision_input["failure_record"])
    assert failure_record["affected_field_paths"] == [
        "$.input_resource_types",
        "$.output_resource_types",
        "$.output_effects",
        "$.disposition",
    ]


def test_selected_analysis_read__stays_answer_only__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "read selected mail",
        "completion_conditions": ["summarized"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-read",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="read this mail",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=PromptReference(
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
        ),
    )

    assert candidate.output_mode == "ANSWER"
    assert candidate.output_pairs == ()
    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.input_reason_codes == (("GMAIL_THREAD", "RESOURCE_SELECTED"),)
    assert candidate.analysis_requirement == "REQUIRED"
    assert runtime.calls == []


def test_selected_simple_read__materializes_exact_route__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "read selected mail",
        "completion_conditions": ["summarized"],
        "constraints": [
            {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["thread-42"]}
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-read",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="read this mail",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.output_mode == "ANSWER"
    assert candidate.input_resource_types == ("GMAIL_THREAD",)
    assert candidate.input_reason_codes == (("GMAIL_THREAD", "RESOURCE_SELECTED"),)


def test_answer_only__materializes_no_tool_route__without_llm() -> None:
    catalog = load_signed_tool_registry()
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-read", "revision": 1, "based_on": []},
        "goal": "answer arithmetic question",
        "completion_conditions": ["answered"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    request = WorkflowStartRequest(
        run_id="run-answer",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="2 + 2",
        selected_resource_ids=(),
        selected_resources=(),
        run_budget=dict(build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    runtime = FakeStructuredInferencePort(outputs=[])

    candidate, _ = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
    )

    assert runtime.calls == []
    assert candidate.input_resource_types == ()
    assert candidate.output_pairs == ()
    assert candidate.output_mode == "ANSWER"
