from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from tests.support.prompt_manifests import write_draft_manifest, write_runtime_active_manifest

from google_work_agent.application.orchestration.contracts import (
    PlanningResult,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ContextRetrievalResultV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.prompt_registry import InactivePromptArtifactError
from google_work_agent.application.orchestration.solution_planning import (
    ACTION_PLAN_DRAFT_OUTPUT_SCHEMA,
    ANSWER_DRAFT_OUTPUT_SCHEMA,
    SolutionPlanningAgent,
    SolutionPlanningValidationError,
    _action_plan_draft_output_schema_for_registry,
    build_solution_planning_clarification_question,
    load_solution_planning_answer_only_prompt_reference,
    load_solution_planning_draft_plan_prompt_reference,
    load_solution_planning_revise_answer_prompt_reference,
    load_solution_planning_revise_plan_prompt_reference,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.orchestration.tool_routing import OutputToolRouteV1
from google_work_agent.domain.tool_registry import SignedToolRegistry, build_p0_tool_registry
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

ANSWER_ONLY_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="planning.answer_only",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="solution_planning",
    subgraph_name="planning",
    node_name="answer_only",
    node_state="BASELINE",
    purpose="answer_only",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
DRAFT_PLAN_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="planning.draft_plan",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="solution_planning",
    subgraph_name="planning",
    node_name="draft_plan",
    node_state="BASELINE",
    purpose="draft_plan",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
REVISE_ANSWER_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="planning.revise_plan",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="solution_planning",
    subgraph_name="planning",
    node_name="revise_plan",
    node_state="BASELINE",
    purpose="revise_plan",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
REVISE_PLAN_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="planning.revise_plan",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="solution_planning",
    subgraph_name="planning",
    node_name="revise_plan",
    node_state="BASELINE",
    purpose="revise_plan",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult | Exception] = field(default_factory=deque)
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
        result = self.queued.popleft()
        if isinstance(result, Exception):
            raise result
        return result


def test_answer_only_stores_answer_draft_and_clears_plan_draft() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_answer_output(PlanningResult.ANSWER_ONLY.value)))
    agent = _agent(runtime)

    result = agent.answer_only(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )
    state_update = agent.build_answer_state_update(result)

    assert set(result) == {
        "schema_version",
        "status",
        "answer",
        "evidence_refs",
        "resource_refs",
        "reason_codes",
        "confirmation",
        "blockers",
        "llm_provider_result",
    }
    assert result["status"] == PlanningResult.ANSWER_ONLY.value
    assert state_update["workflow_phase"] == WorkflowPhase.PLAN_REVIEW.value
    assert state_update["answer_draft"] == result
    assert state_update["plan_draft"] is None
    assert "user_interrupt" not in state_update
    assert cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id == "planning.answer_only"
    assert runtime.calls[0]["output_schema"] == ANSWER_DRAFT_OUTPUT_SCHEMA


def test_answer_only_prompt_input_uses_stage7_outputs_and_marks_source_untrusted() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_answer_output(PlanningResult.ANSWER_ONLY.value)))
    agent = _agent(runtime)

    agent.answer_only(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert prompt_input["request_intent"] == _intent()
    assert prompt_input["context_bundle"] == _context_result()["context_bundle"]
    assert prompt_input["evidence_drafts"] == _context_result()["evidence_drafts"]
    assert prompt_input["analysis_result"] == _analysis_result()
    assert prompt_input["source_content_is_untrusted"] is True
    assert "acquisition_result" not in prompt_input


def test_answer_draft_rejects_invalid_status_and_unknown_refs() -> None:
    output = _answer_output(PlanningResult.ANSWER_ONLY.value)
    output["status"] = "PLAN_READY"

    with pytest.raises(SolutionPlanningValidationError, match="status is invalid"):
        validate_answer_draft_v1(output, analysis_result=_analysis_result())

    output = _answer_output(PlanningResult.ANSWER_ONLY.value)
    cast(list[str], output["evidence_refs"]).append("evidence-x")

    with pytest.raises(SolutionPlanningValidationError, match="evidence reference does not exist"):
        validate_answer_draft_v1(output, analysis_result=_analysis_result())


def test_answer_draft_accepts_route_reconsideration_required_with_reason_codes() -> None:
    """Pre-Prompt Output Contract Alignment: 06-agent-workflow.md SS3.5/3.7
    documents ROUTE_RECONSIDERATION_REQUIRED as a Planning disposition; the
    structured output schema/validator must actually accept it."""
    output = _answer_output(PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value)

    result = validate_answer_draft_v1(output, analysis_result=_analysis_result())

    assert result["status"] == PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value


def test_answer_draft_route_reconsideration_required_without_reason_codes_is_rejected() -> None:
    output = _answer_output(PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value)
    output["reason_codes"] = []

    with pytest.raises(SolutionPlanningValidationError, match="reason_codes"):
        validate_answer_draft_v1(output, analysis_result=_analysis_result())


def test_plan_draft_accepts_route_reconsideration_required_with_no_actions() -> None:
    output = _plan_output(PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value, actions=[])

    result = validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    assert result["status"] == PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value
    assert result["actions"] == []


def test_plan_draft_route_reconsideration_required_with_actions_is_rejected() -> None:
    output = _plan_output(PlanningResult.ROUTE_RECONSIDERATION_REQUIRED.value)

    with pytest.raises(SolutionPlanningValidationError, match="actions"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _answer_output(PlanningResult.ANSWER_ONLY.value)
    cast(list[dict[str, object]], output["resource_refs"])[0]["resource_handle"] = "task:missing"

    with pytest.raises(SolutionPlanningValidationError, match="resource reference does not exist"):
        validate_answer_draft_v1(output, analysis_result=_analysis_result())


def test_answer_draft_needs_confirmation_and_blocked_invariants() -> None:
    output = _answer_output(
        PlanningResult.NEEDS_CONFIRMATION.value,
        confirmation={"reason_code": "MISSING_SCOPE", "question": "Which recipient?"},
    )
    result = validate_answer_draft_v1(output, analysis_result=_analysis_result())

    assert result["status"] == PlanningResult.NEEDS_CONFIRMATION.value
    assert result["confirmation"] is not None

    output = _answer_output(PlanningResult.BLOCKED.value, blockers=["No supported answer path."])
    blocked = validate_answer_draft_v1(output, analysis_result=_analysis_result())

    assert blocked["status"] == PlanningResult.BLOCKED.value
    assert blocked["blockers"] == ["No supported answer path."]

    output = _answer_output(PlanningResult.NEEDS_CONFIRMATION.value)
    with pytest.raises(SolutionPlanningValidationError, match="requires confirmation"):
        validate_answer_draft_v1(output, analysis_result=_analysis_result())


def test_draft_plan_builds_plan_ready_and_stores_plan_draft_only() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_plan_output(PlanningResult.PLAN_READY.value)))
    agent = _agent(runtime)

    result = agent.draft_plan(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )
    state_update = agent.build_plan_state_update(result)

    assert result["status"] == PlanningResult.PLAN_READY.value
    assert len(result["actions"]) == 2
    assert result["confirmation"] is None
    assert state_update["workflow_phase"] == WorkflowPhase.PLAN_REVIEW.value
    assert state_update["plan_draft"] == result
    assert state_update["answer_draft"] is None
    assert cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id == "planning.draft_plan"
    assert runtime.calls[0]["output_schema"] == _action_plan_draft_output_schema_for_registry(
        build_p0_tool_registry()
    )


def test_action_plan_draft_output_schema_reflects_injected_tool_registry() -> None:
    """Contract: tool_name is constrained to the tool_registry actually
    injected into this SolutionPlanningAgent instance, not a hardcoded P0
    enum -- so a non-default registry never gets schema-rejected for its
    own legitimately-registered tool names."""
    full_entries = build_p0_tool_registry().list_entries()
    custom_registry = SignedToolRegistry(full_entries[:1])

    schema = _action_plan_draft_output_schema_for_registry(custom_registry)

    properties = cast(dict[str, object], schema.json_schema["properties"])
    actions_schema = cast(dict[str, object], properties["actions"])
    item_schema = cast(dict[str, object], actions_schema["items"])
    item_properties = cast(dict[str, object], item_schema["properties"])
    tool_name_schema = cast(dict[str, object], item_properties["tool_name"])

    assert tool_name_schema["enum"] == [full_entries[0].tool_name]


def test_action_plan_cannot_escape_frozen_output_route() -> None:
    output = _plan_output(
        PlanningResult.PLAN_READY.value,
        actions=[
            _action(
                "action-1",
                1,
                effect="CREATE",
                tool_name="tasks_create_task",
                evidence_refs=["evidence-1"],
                resource_refs=["gmail_thread:thread-kim"],
            )
        ],
        evidence_refs=["evidence-1"],
    )
    frozen_routes: tuple[OutputToolRouteV1, ...] = (
        {
            "route_id": "route-1",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "calendar_create_event",
            "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
        },
    )

    with pytest.raises(SolutionPlanningValidationError, match="escapes frozen output route"):
        validate_action_plan_draft_v1(
            output,
            analysis_result=_analysis_result(),
            frozen_output_routes=frozen_routes,
        )


def test_invoke_draft_plan_llm_scopes_tool_name_enum_to_agent_tool_registry() -> None:
    full_entries = build_p0_tool_registry().list_entries()
    custom_registry = SignedToolRegistry(full_entries[:1])
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_plan_output(PlanningResult.PLAN_READY.value)))
    agent = SolutionPlanningAgent(
        llm_runtime=runtime,
        answer_only_prompt_ref=ANSWER_ONLY_PROMPT_REF,
        draft_plan_prompt_ref=DRAFT_PLAN_PROMPT_REF,
        revise_answer_prompt_ref=REVISE_ANSWER_PROMPT_REF,
        revise_plan_prompt_ref=REVISE_PLAN_PROMPT_REF,
        tool_registry=custom_registry,
    )

    agent.invoke_draft_plan_llm(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert output_schema == _action_plan_draft_output_schema_for_registry(custom_registry)


def test_invoke_answer_only_llm_wires_semantic_validate_to_validate_answer_draft_v1() -> None:
    """Regression for the D-2-class repair-boundary gap: invoke_answer_only_llm
    must pass validate_answer_draft_v1 as semantic_validate."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_answer_output(PlanningResult.ANSWER_ONLY.value)))
    agent = _agent(runtime)

    agent.answer_only(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    semantic_validate = cast("Callable[[object], object]", runtime.calls[0]["semantic_validate"])
    assert semantic_validate is not None
    repaired = cast(
        "dict[str, object]", semantic_validate(_answer_output(PlanningResult.ANSWER_ONLY.value))
    )
    assert repaired["status"] == PlanningResult.ANSWER_ONLY.value
    invalid = _answer_output(PlanningResult.ANSWER_ONLY.value)
    invalid["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(SolutionPlanningValidationError):
        semantic_validate(invalid)


def test_invoke_draft_plan_llm_wires_semantic_validate_to_validate_action_plan_draft_v1() -> None:
    """Regression for the D-2-class repair-boundary gap: invoke_draft_plan_llm
    must pass validate_action_plan_draft_v1 as semantic_validate."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_plan_output(PlanningResult.PLAN_READY.value)))
    agent = _agent(runtime)

    agent.draft_plan(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    semantic_validate = cast("Callable[[object], object]", runtime.calls[0]["semantic_validate"])
    assert semantic_validate is not None
    repaired = cast(
        "dict[str, object]", semantic_validate(_plan_output(PlanningResult.PLAN_READY.value))
    )
    assert repaired["status"] == PlanningResult.PLAN_READY.value
    invalid = _plan_output(PlanningResult.PLAN_READY.value)
    invalid["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(SolutionPlanningValidationError):
        semantic_validate(invalid)


def test_revise_answer_uses_existing_answer_and_review_issues() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            _answer_output(
                PlanningResult.ANSWER_ONLY.value,
                blockers=[],
            )
        )
    )
    agent = _agent(runtime)
    answer_draft = validate_answer_draft_v1(
        _answer_output(PlanningResult.ANSWER_ONLY.value),
        analysis_result=_analysis_result(),
    )
    review_issues = [_review_issue()]

    result = agent.revise_answer(
        request_intent=_intent(),
        answer_draft=answer_draft,
        review_issues=review_issues,
        review_summary="The answer omitted the pending task context.",
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    prompt_ref = cast(PromptReference, runtime.calls[0]["prompt_ref"])
    assert prompt_ref.prompt_id == "planning.revise_plan"
    assert runtime.calls[0]["output_schema"] == ANSWER_DRAFT_OUTPUT_SCHEMA
    assert prompt_input["answer_draft"] == answer_draft
    assert prompt_input["review_summary"] == "The answer omitted the pending task context."
    assert prompt_input["review_issues"] == review_issues
    assert prompt_input["analysis_result"] == _analysis_result()
    assert prompt_input["source_content_is_untrusted"] is True
    assert result["status"] == PlanningResult.ANSWER_ONLY.value


def test_revise_plan_uses_existing_plan_and_review_issues() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            _plan_output(
                PlanningResult.PLAN_READY.value,
                actions=[
                    _action(
                        "action-1",
                        1,
                        effect="READ",
                        tool_name="gmail_get_thread",
                        evidence_refs=["evidence-1"],
                        resource_refs=["gmail_thread:thread-kim"],
                    )
                ],
                evidence_refs=["evidence-1"],
            )
        )
    )
    agent = _agent(runtime)
    plan_draft = validate_action_plan_draft_v1(
        _plan_output(PlanningResult.PLAN_READY.value),
        analysis_result=_analysis_result(),
    )
    review_issues = [_plan_review_issue()]

    result = agent.revise_plan(
        request_intent=_intent(),
        plan_draft=plan_draft,
        review_issues=review_issues,
        review_summary="Remove the unnecessary task creation step.",
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    prompt_ref = cast(PromptReference, runtime.calls[0]["prompt_ref"])
    assert prompt_ref.prompt_id == "planning.revise_plan"
    assert runtime.calls[0]["output_schema"] == ACTION_PLAN_DRAFT_OUTPUT_SCHEMA
    assert prompt_input["plan_draft"] == plan_draft
    assert prompt_input["review_summary"] == "Remove the unnecessary task creation step."
    assert prompt_input["review_issues"] == review_issues
    assert prompt_input["analysis_result"] == _analysis_result()
    assert prompt_input["source_content_is_untrusted"] is True
    assert result["status"] == PlanningResult.PLAN_READY.value


def test_revise_plan_state_update_replaces_plan_and_clears_answer_draft() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            _plan_output(
                PlanningResult.PLAN_READY.value,
                actions=[
                    _action(
                        "action-1",
                        1,
                        effect="READ",
                        tool_name="gmail_get_thread",
                        evidence_refs=["evidence-1"],
                        resource_refs=["gmail_thread:thread-kim"],
                    )
                ],
                evidence_refs=["evidence-1"],
            )
        )
    )
    agent = _agent(runtime)
    revised = agent.revise_plan(
        request_intent=_intent(),
        plan_draft=validate_action_plan_draft_v1(
            _plan_output(PlanningResult.PLAN_READY.value),
            analysis_result=_analysis_result(),
        ),
        review_issues=[_plan_review_issue()],
        review_summary="Remove the unnecessary task creation step.",
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    state_update = agent.build_plan_state_update(revised)

    assert state_update["workflow_phase"] == WorkflowPhase.PLAN_REVIEW.value
    assert state_update["plan_draft"] == revised
    assert state_update["answer_draft"] is None


def test_revise_plan_confirmation_uses_existing_contract() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            _plan_output(
                PlanningResult.NEEDS_CONFIRMATION.value,
                actions=[],
                confirmation={
                    "reason_code": "MISSING_SCOPE",
                    "question": "Should we still create a follow-up task?",
                },
            )
        )
    )
    agent = _agent(runtime)

    result = agent.revise_plan(
        request_intent=_intent(),
        plan_draft=validate_action_plan_draft_v1(
            _plan_output(PlanningResult.PLAN_READY.value),
            analysis_result=_analysis_result(),
        ),
        review_issues=[_plan_review_issue()],
        review_summary="Clarify whether the task should remain.",
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    assert result["status"] == PlanningResult.NEEDS_CONFIRMATION.value
    assert result["confirmation"] is not None


def test_plan_prompt_input_uses_stage7_outputs_and_marks_source_untrusted() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_plan_output(PlanningResult.PLAN_READY.value)))
    agent = _agent(runtime)

    agent.draft_plan(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert prompt_input["request_intent"] == _intent()
    assert prompt_input["context_bundle"] == _context_result()["context_bundle"]
    assert prompt_input["analysis_result"] == _analysis_result()
    assert prompt_input["source_content_is_untrusted"] is True


def test_action_plan_rejects_invalid_refs_duplicate_ids_and_dependency_errors() -> None:
    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["tool_name"] = "gmail_delete_message"

    with pytest.raises(SolutionPlanningValidationError, match="tool not registered"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["effect"] = "UPDATE"

    with pytest.raises(SolutionPlanningValidationError, match="effect does not match tool policy"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["action_id"] = "action-2"

    with pytest.raises(SolutionPlanningValidationError, match="duplicate action_id"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["depends_on_action_ids"] = ["missing"]

    with pytest.raises(SolutionPlanningValidationError, match="dependency not found"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["depends_on_action_ids"] = ["action-1"]

    with pytest.raises(SolutionPlanningValidationError, match="depend on itself"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["depends_on_action_ids"] = ["action-2"]
    cast(list[dict[str, object]], output["actions"])[1]["depends_on_action_ids"] = ["action-1"]

    with pytest.raises(SolutionPlanningValidationError, match="cycle"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())


def test_action_plan_rejects_unknown_refs_and_requires_plan_level_coverage() -> None:
    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["evidence_refs"] = ["evidence-x"]

    with pytest.raises(SolutionPlanningValidationError, match="evidence reference does not exist"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[dict[str, object]], output["actions"])[0]["resource_refs"] = ["task:missing"]

    with pytest.raises(SolutionPlanningValidationError, match="resource reference does not exist"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(PlanningResult.PLAN_READY.value)
    cast(list[str], output["evidence_refs"]).remove("evidence-2")

    with pytest.raises(SolutionPlanningValidationError, match="covered by plan evidence_refs"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())


def test_action_plan_accepts_send_and_delete_registered_tools() -> None:
    send_output = _plan_output(
        PlanningResult.PLAN_READY.value,
        actions=[
            _action(
                "action-send",
                1,
                effect="SEND",
                tool_name="gmail_send",
                evidence_refs=["evidence-1"],
                resource_refs=["gmail_thread:thread-kim"],
            )
        ],
        evidence_refs=["evidence-1"],
    )
    delete_output = _plan_output(
        PlanningResult.PLAN_READY.value,
        actions=[
            _action(
                "action-delete",
                1,
                effect="DELETE",
                tool_name="calendar_delete_event",
                evidence_refs=["evidence-1", "evidence-2"],
                resource_refs=["gmail_thread:thread-kim"],
            )
        ],
        evidence_refs=["evidence-1", "evidence-2"],
    )

    send_result = validate_action_plan_draft_v1(send_output, analysis_result=_analysis_result())
    delete_result = validate_action_plan_draft_v1(delete_output, analysis_result=_analysis_result())

    assert send_result["actions"][0]["effect"] == "SEND"
    assert send_result["actions"][0]["tool_name"] == "gmail_send"
    assert delete_result["actions"][0]["effect"] == "DELETE"
    assert delete_result["actions"][0]["tool_name"] == "calendar_delete_event"


def test_action_plan_needs_confirmation_or_blocked_do_not_store_actions() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            _plan_output(
                PlanningResult.NEEDS_CONFIRMATION.value,
                actions=[],
                confirmation={
                    "reason_code": "MISSING_SCOPE",
                    "question": "Should we create the follow-up task?",
                },
            )
        )
    )
    agent = _agent(runtime)

    result = agent.draft_plan(
        request_intent=_intent(),
        context_result=_context_result(),
        analysis_result=_analysis_result(),
        request=_request(),
    )
    state_update = agent.build_plan_state_update(result)
    clarification = build_solution_planning_clarification_question(
        result=result,
        request_intent=_intent(),
    )

    assert result["status"] == PlanningResult.NEEDS_CONFIRMATION.value
    assert result["actions"] == []
    assert result["confirmation"] is not None
    assert state_update["plan_draft"] is None
    assert state_update["answer_draft"] is None
    assert "user_interrupt" not in state_update
    assert clarification["origin_target"] == "planning.draft_plan"

    output = _plan_output(PlanningResult.BLOCKED.value, actions=[])
    blocked = validate_action_plan_draft_v1(output, analysis_result=_analysis_result())
    assert blocked["status"] == PlanningResult.BLOCKED.value


def test_action_plan_confirmation_invariants_are_enforced() -> None:
    output = _plan_output(
        PlanningResult.NEEDS_CONFIRMATION.value,
        actions=[],
        confirmation=None,
    )

    with pytest.raises(SolutionPlanningValidationError, match="requires confirmation"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())

    output = _plan_output(
        PlanningResult.PLAN_READY.value,
        confirmation={
            "reason_code": "MISSING_SCOPE",
            "question": "Should we create the follow-up task?",
        },
    )

    with pytest.raises(SolutionPlanningValidationError, match="must not include confirmation"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())


def test_update_action_uses_existing_policy_validator() -> None:
    output = _plan_output(
        PlanningResult.PLAN_READY.value,
        actions=[
            _action(
                "action-1",
                1,
                effect="UPDATE",
                tool_name="tasks_update_task",
                evidence_refs=["evidence-1"],
                resource_refs=["gmail_thread:thread-kim"],
                target_resource_ref_id=None,
            )
        ],
        evidence_refs=["evidence-1"],
    )

    with pytest.raises(SolutionPlanningValidationError, match="existing resource updates require"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())


def test_task_provider_due_is_rejected_by_plan_semantic_validation() -> None:
    action = _action(
        "action-1",
        1,
        effect="CREATE",
        tool_name="tasks_create_task",
        evidence_refs=["evidence-1"],
        resource_refs=["gmail_thread:thread-kim"],
    )
    action["arguments"] = {
        "task_list_id": "task-list-default",
        "payload": {"title": "보고서 정리", "due": "2026-08-12"},
    }
    output = _plan_output(
        PlanningResult.PLAN_READY.value,
        actions=[action],
        evidence_refs=["evidence-1"],
    )

    with pytest.raises(SolutionPlanningValidationError, match="Provider-boundary field"):
        validate_action_plan_draft_v1(output, analysis_result=_analysis_result())


def test_provider_failure_is_not_mapped_to_blocked() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(RuntimeError("provider unavailable"))
    agent = _agent(runtime)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        agent.answer_only(
            request_intent=_intent(),
            context_result=_context_result(),
            analysis_result=_analysis_result(),
            request=_request(),
        )


def test_answer_only_and_plan_source_have_no_google_mcp_or_completion_call() -> None:
    source = Path("src/google_work_agent/application/orchestration/solution_planning.py").read_text(
        encoding="utf-8"
    )

    assert "GoogleWorkspaceGateway" not in source
    assert "MCP" not in source
    assert "complete_answer_only_run" not in source
    assert "PublishReadOnlyPlanCommand" not in source


def test_prompt_refs_are_runtime_active(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path,
        prompt_ids={
            "planning.compose_answer",
            "planning.compose_arguments",
            "planning.compose_arguments.revise",
            "planning.compose_answer.revise",
        },
    )
    answer_prompt = load_solution_planning_answer_only_prompt_reference(manifest_path)
    plan_prompt = load_solution_planning_draft_plan_prompt_reference(manifest_path)
    revise_prompt = load_solution_planning_revise_answer_prompt_reference(manifest_path)
    revise_plan_prompt = load_solution_planning_revise_plan_prompt_reference(manifest_path)

    assert answer_prompt.prompt_id == "planning.compose_answer"
    assert answer_prompt.prompt_version == "0.9.0"
    assert answer_prompt.content_hash
    assert answer_prompt.node_state == "INITIAL"
    assert answer_prompt.output_schema_version == "r8.6-output-contract-snapshot-v1"

    assert plan_prompt.prompt_id == "planning.compose_arguments"
    assert plan_prompt.prompt_version == "0.9.0"
    assert plan_prompt.content_hash
    assert plan_prompt.node_state == "INITIAL"
    assert plan_prompt.output_schema_version == "r8.6-output-contract-snapshot-v1"

    assert revise_prompt.prompt_id == "planning.compose_answer.revise"
    assert revise_prompt.prompt_version == "0.9.0"
    assert revise_prompt.content_hash
    assert revise_prompt.node_state == "SEMANTIC_REVISION"
    assert revise_prompt.output_schema_version == "r8.6-output-contract-snapshot-v1"

    assert revise_plan_prompt.prompt_id == "planning.compose_arguments.revise"
    assert revise_plan_prompt.prompt_version == "0.9.0"
    assert revise_plan_prompt.content_hash
    assert revise_plan_prompt.node_state == "SEMANTIC_REVISION"
    assert revise_plan_prompt.output_schema_version == "r8.6-output-contract-snapshot-v1"


def test_default_product_loader_rejects_draft_planning_prompts(tmp_path: Path) -> None:
    manifest_path = write_draft_manifest(tmp_path, prompt_ids={"planning.compose_answer"})
    with pytest.raises(InactivePromptArtifactError, match="planning.compose_answer"):
        load_solution_planning_answer_only_prompt_reference(manifest_path)


def test_solution_planning_symbols_have_explicit_owners() -> None:
    assert SolutionPlanningAgent.__module__.endswith(".orchestration.solution_planning")
    assert validate_answer_draft_v1.__module__.endswith(".orchestration.solution_planning")
    assert validate_action_plan_draft_v1.__module__.endswith(".orchestration.solution_planning")


def _agent(runtime: FakeLLMRuntime) -> SolutionPlanningAgent:
    return SolutionPlanningAgent(
        llm_runtime=runtime,
        answer_only_prompt_ref=ANSWER_ONLY_PROMPT_REF,
        draft_plan_prompt_ref=DRAFT_PLAN_PROMPT_REF,
        revise_answer_prompt_ref=REVISE_ANSWER_PROMPT_REF,
        revise_plan_prompt_ref=REVISE_PLAN_PROMPT_REF,
    )


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Plan the next response or actions for Kim's follow-up.",
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
        "goal": "Handle Kim's follow-up",
        "completion_conditions": ["Produce an answer or an action plan draft."],
        "constraints": [
            {"kind": "PERSON", "field": "person", "value": "Kim"},
        ],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def _context_result() -> ContextRetrievalResultV1:
    return {
        "schema_version": 1,
        "status": "SUFFICIENT",
        "context_bundle": {
            "schema_version": 1,
            "resource_refs": [
                {
                    "resource_handle": "gmail_thread:thread-kim",
                    "source": "GMAIL",
                    "resource_type": "gmail_thread",
                    "resource_id": "thread-kim",
                    "parent_id": None,
                    "version": "1",
                }
            ],
            "segment_refs": [
                {
                    "segment_id": "seg-1",
                    "resource_handle": "gmail_thread:thread-kim",
                    "source": "GMAIL",
                    "locator": {"kind": "resource_payload"},
                }
            ],
            "evidence_refs": ["evidence-1", "evidence-2"],
            "normalized_context": [
                {
                    "evidence_id": "evidence-1",
                    "resource_handle": "gmail_thread:thread-kim",
                    "segment_id": "seg-1",
                    "kind": "excerpt",
                    "excerpt": "Kim is waiting for a follow-up response.",
                }
            ],
            "missing_information": [],
            "ambiguity": None,
        },
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "seg-1",
                "kind": "excerpt",
                "excerpt": "Kim is waiting for a follow-up response.",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            },
            {
                "schema_version": 1,
                "evidence_id": "evidence-2",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "seg-1",
                "kind": "excerpt",
                "excerpt": "The task update is still pending.",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            },
        ],
        "selected_segment_ids": ["seg-1"],
        "excluded_resource_handles": [],
        "missing_slots": [],
        "additional_acquisition_request": None,
        "sufficiency": {
            "schema_version": 1,
            "reason_codes": ["CONTEXT_READY"],
            "summary": "Context is ready for planning.",
        },
        "llm_provider_result": {"provider": "fake"},
    }


def _analysis_result() -> WorkAnalysisResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "A follow-up response is required and a task update may be needed.",
        "findings": [
            {
                "schema_version": 1,
                "finding_id": "finding-1",
                "kind": "RELATIONSHIP",
                "statement": "The Gmail thread is related to the pending follow-up task.",
                "evidence_refs": ["evidence-1", "evidence-2"],
                "resource_refs": ["gmail_thread:thread-kim"],
                "segment_refs": ["seg-1"],
                "related_resource_handles": ["gmail_thread:thread-kim"],
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["evidence-1", "evidence-2"],
        "resource_refs": _context_result()["context_bundle"]["resource_refs"],
        "segment_refs": _context_result()["context_bundle"]["segment_refs"],
        "additional_acquisition_request": None,
        "llm_provider_result": {"provider": "fake"},
    }


def _answer_output(
    status: str,
    *,
    confirmation: dict[str, object] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    if blockers is None:
        blockers = ["No supported answer path."] if status == PlanningResult.BLOCKED.value else []
    return {
        "schema_version": 1,
        "status": status,
        "answer": "We have enough context to explain the pending follow-up to the user.",
        "evidence_refs": ["evidence-1", "evidence-2"],
        "resource_refs": _analysis_result()["resource_refs"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
        "confirmation": confirmation,
        "blockers": blockers,
    }


def _plan_output(
    status: str,
    *,
    actions: list[dict[str, object]] | None = None,
    evidence_refs: list[str] | None = None,
    confirmation: dict[str, object] | None = None,
) -> dict[str, object]:
    if actions is None:
        actions = [
            _action(
                "action-1",
                1,
                effect="READ",
                tool_name="gmail_get_thread",
                evidence_refs=["evidence-1"],
                resource_refs=["gmail_thread:thread-kim"],
            ),
            _action(
                "action-2",
                2,
                effect="CREATE",
                tool_name="tasks_create_task",
                evidence_refs=["evidence-1", "evidence-2"],
                resource_refs=["gmail_thread:thread-kim"],
                depends_on_action_ids=["action-1"],
            ),
        ]
    if evidence_refs is None:
        evidence_refs = ["evidence-1", "evidence-2"]
    return {
        "schema_version": 2,
        "status": status,
        "plan_id": "plan-1",
        "summary": "Prepare a follow-up response and optional next-step task.",
        "objective": "Resolve Kim's follow-up with a clear next action.",
        "actions": actions,
        "evidence_refs": evidence_refs,
        "resource_refs": _analysis_result()["resource_refs"],
        "confirmation": confirmation,
    }


def _action(
    action_id: str,
    position: int,
    *,
    effect: str,
    tool_name: str,
    evidence_refs: list[str],
    resource_refs: list[str],
    target_resource_ref_id: str | None = None,
    depends_on_action_ids: list[str] | None = None,
) -> dict[str, object]:
    if depends_on_action_ids is None:
        depends_on_action_ids = []
    return {
        "schema_version": 2,
        "action_id": action_id,
        "position": position,
        "effect": effect,
        "tool_name": tool_name,
        "arguments": {"query": "follow-up", "payload": {"title": "Follow up with Kim"}},
        "expected": {"result": "available"},
        "evidence_refs": evidence_refs,
        "resource_refs": resource_refs,
        "target_resource_ref_id": target_resource_ref_id,
        "depends_on_action_ids": depends_on_action_ids,
        "user_visible_reason": "This action supports the follow-up requested by the user.",
    }


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        latency_ms=5,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="provider-request-1",
        safe_error_code=None,
    )


def _review_issue() -> dict[str, object]:
    return {
        "issue_id": "issue-1",
        "kind": "MISSING_GOAL_COVERAGE",
        "message": "Mention the pending task context in the answer.",
        "evidence_refs": ["evidence-2"],
        "resource_refs": ["gmail_thread:thread-kim"],
    }


def _plan_review_issue() -> dict[str, object]:
    return {
        "issue_id": "issue-1",
        "kind": "UNNECESSARY_ACTION",
        "message": "Remove the unnecessary follow-up task creation step.",
        "affected_action_ids": ["action-2"],
        "affected_field_paths": ["$.actions[1]"],
        "evidence_refs": ["evidence-2"],
        "resource_refs": ["gmail_thread:thread-kim"],
        "reason_codes": ["SCOPE_EXCEEDED"],
    }
