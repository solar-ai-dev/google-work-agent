from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from tests.support.prompt_manifests import write_draft_manifest, write_runtime_active_manifest

from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    ClarificationQuestionV1,
    ConfirmationResponseKind,
    RequestUnderstandingAgent,
    RequestUnderstandingResult,
    RequestUnderstandingValidationError,
    WorkflowPhase,
    build_user_interrupt_v1,
    load_request_understanding_clarify_prompt_reference,
    resolve_confirmation_origin_target,
    validate_confirmation_response_v1,
    validate_request_intent_v1,
)
from google_work_agent.application.workflows.prompt_registry import InactivePromptArtifactError
from google_work_agent.ports import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="request_understanding.classify",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="request_understanding",
    subgraph_name="request_understanding",
    node_name="classify",
    node_state="BASELINE",
    purpose="classify",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
CLARIFY_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="request_understanding.clarify",
    prompt_version="v0.1",
    content_hash="hash-clarify",
    agent_role="request_understanding",
    subgraph_name="request_understanding",
    node_name="clarify",
    node_state="BASELINE",
    purpose="clarify",
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


def test_clear_request_returns_complete_request_intent() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_clear_intent()))
    request = _request("김대리 메일 찾아서 이번 주 해야 할 일 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(request)
    state_update = agent.build_state_update(output, request=request)

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert output["request_intent"] is not None
    assert output["request_intent"]["schema_version"] == 2
    assert output["request_intent"]["goal"]["summary"] == "김대리 관련 메일에서 할 일 정리"
    assert output["clarification"] is None
    assert output["failure"] is None
    assert state_update["workflow_phase"] == WorkflowPhase.REQUEST_ANALYSIS.value
    assert state_update["request_intent"] == output["request_intent"]
    assert runtime.calls[0]["prompt_input"] == {
        "request_text": request.request_text,
        "entry_mode": "AGENT_SEARCH",
        "selected_resource_ids": [],
    }
    assert cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id == (
        "request_understanding.classify"
    )


def test_invoke_classify_llm_wires_semantic_validate_to_validate_request_intent_v1() -> None:
    """Regression for the D-2-class repair-boundary gap: invoke_classify_llm
    must pass validate_request_intent_v1 as semantic_validate so a
    schema-shape-valid but semantically-invalid output (e.g. a bad
    schema_version) is repair-eligible instead of raising uncaught from
    build_output_from_llm_result."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_clear_intent()))
    request = _request("김대리 메일 찾아서 이번 주 해야 할 일 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    agent.classify(request)

    semantic_validate = runtime.calls[0]["semantic_validate"]
    assert semantic_validate is validate_request_intent_v1
    assert semantic_validate(_clear_intent())["schema_version"] == 2
    invalid = _clear_intent()
    invalid["schema_version"] = 99
    with pytest.raises(RequestUnderstandingValidationError):
        semantic_validate(invalid)


def test_linguistically_ambiguous_request_needs_confirmation() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_ambiguous_intent()))
    request = _request("그 사람이랑 얘기했던 일정 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(request)
    state_update = agent.build_state_update(output, request=request)

    assert output["result"] == RequestUnderstandingResult.NEEDS_CONFIRMATION.value
    assert output["request_intent"] is not None
    assert output["clarification"] == {
        "schema_version": 1,
        "origin_target": "request_understanding.classify",
        "question": "어떤 사람을 말하는지 알려주세요.",
        "affected_field_paths": ["semantic_constraints.people[0]"],
        "reason_code": "INTENT_AMBIGUITY_MISSED",
        "known_context_summary": "그 사람과 이야기했던 일정 정리",
        "options": [],
    }
    assert output["failure"] is None
    assert state_update["workflow_phase"] == WorkflowPhase.REQUEST_ANALYSIS.value
    assert "user_interrupt" not in state_update


def test_retrieval_candidate_ambiguity_is_not_confirmed_by_request_understanding() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_minsu_intent()))
    request = _request("민수랑 얘기했던 일정 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(request)

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert output["clarification"] is None
    assert output["request_intent"] is not None
    assert output["request_intent"]["semantic_constraints"]["people"][0]["mention"] == "민수"


def test_unsupported_scope_returns_invalid_without_request_intent_handoff() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_unsupported_intent()))
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(_request("메일 전부 삭제해줘."))
    state_update = agent.build_state_update(output, request=_request("메일 전부 삭제해줘."))

    assert output["result"] == RequestUnderstandingResult.INVALID.value
    assert output["request_intent"] is None
    assert output["clarification"] is None
    assert output["failure"] == {
        "schema_version": 1,
        "reason_code": "INTENT_UNSUPPORTED_SCOPE",
        "user_safe_message": "삭제 요청은 현재 제품 범위에서 처리할 수 없습니다.",
        "diagnostic": "RequestIntentV1.unsupported_scope.is_unsupported=true",
    }
    assert state_update["workflow_phase"] == WorkflowPhase.FINALIZE.value
    assert "user_interrupt" not in state_update


def test_structured_output_schema_error_is_not_converted_to_invalid() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "structured output did not satisfy schema",
        )
    )
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    try:
        agent.classify(_request("김대리 메일 찾아줘."))
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    else:
        raise AssertionError("expected schema failure to stay an LLM invocation failure")


def test_structured_output_repair_owned_by_llm_runtime_and_not_retried_by_agent() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_clear_intent(), attempts=2))
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(_request("김대리 메일 찾아서 이번 주 해야 할 일 정리해줘."))

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert output["llm_provider_result"]["structured_output_attempts"] == 2
    assert len(runtime.calls) == 1


def test_resource_selected_preserves_selected_resource_context_without_intent_duplication() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_clear_intent()))
    request = _request(
        "이 메일 기준으로 해야 할 일 정리해줘.",
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=("gmail-thread-1",),
    )
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(request)
    state_update = agent.build_state_update(output, request=request)

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert runtime.calls[0]["prompt_input"] == {
        "request_text": request.request_text,
        "entry_mode": "RESOURCE_SELECTED",
        "selected_resource_ids": ["gmail-thread-1"],
    }
    assert "selected_resource_ids" not in cast(dict[str, object], output["request_intent"])
    assert state_update["prompt_context"] == {
        "entry_mode": "RESOURCE_SELECTED",
        "selected_resource_ids": ["gmail-thread-1"],
    }


def test_agent_surface_has_no_google_mcp_or_action_dependency() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_clear_intent()))
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    output = agent.classify(_request("김대리 메일 찾아줘."))

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert len(runtime.calls) == 1


def test_clarify_prompt_ref_is_runtime_active(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path,
        prompt_ids={"request_understanding.clarify"},
    )
    prompt_ref = load_request_understanding_clarify_prompt_reference(manifest_path)

    assert prompt_ref.prompt_id == "request_understanding.clarify"
    assert prompt_ref.prompt_version == "0.8.3"
    assert prompt_ref.content_hash
    assert prompt_ref.node_state == "CLARIFY"
    assert prompt_ref.output_schema_version == "v2"


def test_default_product_loader_rejects_draft_request_understanding_prompt(tmp_path: Path) -> None:
    manifest_path = write_draft_manifest(
        tmp_path,
        prompt_ids={"request_understanding.clarify"},
    )

    with pytest.raises(InactivePromptArtifactError, match="request_understanding.clarify"):
        load_request_understanding_clarify_prompt_reference(manifest_path)


def test_clarify_invokes_prompt_and_validates_question_output() -> None:
    runtime = FakeLLMRuntime()
    clarification_source: ClarificationQuestionV1 = {
        "schema_version": 1,
        "origin_target": "analysis.analyze",
        "question": "Which task should be treated as the primary follow-up?",
        "affected_field_paths": [],
        "reason_code": "ANALYSIS_RELATIONSHIP_AMBIGUITY",
        "known_context_summary": "Find the primary follow-up task",
        "options": [{"option_id": "task-1", "label": "Task 1"}],
    }
    runtime.queued.append(_llm_result(dict(clarification_source)))
    agent = RequestUnderstandingAgent(
        llm_runtime=runtime,
        prompt_ref=PROMPT_REF,
        clarify_prompt_ref=CLARIFY_PROMPT_REF,
    )

    result = agent.clarify(clarification_source, request=_request("Which task is primary?"))

    assert result == clarification_source
    assert cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id == (
        "request_understanding.clarify"
    )
    assert runtime.calls[0]["prompt_input"] == {
        "request_text": "Which task is primary?",
        "clarification_source": clarification_source,
    }


def test_confirmation_response_contract_and_origin_resolution_are_deterministic() -> None:
    user_interrupt = build_user_interrupt_v1(
        {
            "schema_version": 1,
            "origin_target": "planning.draft_plan",
            "question": "Should we create the follow-up task?",
            "affected_field_paths": [],
            "reason_code": "MISSING_SCOPE",
            "known_context_summary": "Handle Kim's follow-up",
            "options": [{"option_id": "create-task", "label": "Create task"}],
        }
    )

    selection = validate_confirmation_response_v1(
        {
            "schema_version": 1,
            "response_kind": ConfirmationResponseKind.OPTION_SELECTION.value,
            "selected_option_ids": ["create-task"],
            "free_text": None,
        }
    )
    free_text = validate_confirmation_response_v1(
        {
            "schema_version": 1,
            "response_kind": ConfirmationResponseKind.FREE_TEXT.value,
            "selected_option_ids": [],
            "free_text": "Use the existing draft only.",
        }
    )

    assert selection["selected_option_ids"] == ["create-task"]
    assert free_text["free_text"] == "Use the existing draft only."
    assert (
        resolve_confirmation_origin_target(user_interrupt=user_interrupt, response=selection)
        == "planning.draft_plan"
    )

    with pytest.raises(ValueError, match="OPTION_SELECTION requires at least one"):
        validate_confirmation_response_v1(
            {
                "schema_version": 1,
                "response_kind": ConfirmationResponseKind.OPTION_SELECTION.value,
                "selected_option_ids": [],
                "free_text": None,
            }
        )

    with pytest.raises(ValueError, match="FREE_TEXT requires non-empty free_text"):
        validate_confirmation_response_v1(
            {
                "schema_version": 1,
                "response_kind": ConfirmationResponseKind.FREE_TEXT.value,
                "selected_option_ids": [],
                "free_text": "   ",
            }
        )

    with pytest.raises(Exception, match="unknown clarification option_id"):
        resolve_confirmation_origin_target(
            user_interrupt=user_interrupt,
            response={
                "schema_version": 1,
                "response_kind": ConfirmationResponseKind.OPTION_SELECTION.value,
                "selected_option_ids": ["unknown-option"],
                "free_text": None,
            },
        )


def test_request_understanding_exports_do_not_change_existing_workflow_contracts() -> None:
    from google_work_agent.application import workflows

    assert workflows.RequestUnderstandingResult is RequestUnderstandingResult
    assert workflows.WorkflowPhase is WorkflowPhase
    assert hasattr(workflows, "RequestUnderstandingAgent")
    assert hasattr(workflows, "RequestIntentV1")
    assert hasattr(workflows, "load_request_understanding_clarify_prompt_reference")
    assert hasattr(workflows, "resolve_confirmation_origin_target")


def _request(
    request_text: str,
    *,
    entry_mode: str = "AGENT_SEARCH",
    selected_resource_ids: tuple[str, ...] = (),
) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode=entry_mode,
        requested_mode="AUTO",
        request_text=request_text,
        selected_resource_ids=selected_resource_ids,
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _llm_result(payload: dict[str, object], *, attempts: int = 1) -> StructuredLLMResult:
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
        structured_output_attempts=attempts,
        provider_request_id="provider-request-1",
        safe_error_code=None,
    )


def _base_intent() -> dict[str, object]:
    return {
        "schema_version": 2,
        "goal": {
            "summary": "김대리 관련 메일에서 할 일 정리",
            "user_visible_objective": "김대리 메일에서 이번 주 해야 할 일을 정리",
        },
        "completion_criteria": ["관련 메일을 찾고 이번 주 해야 할 일을 요약한다."],
        "semantic_constraints": {
            "topics": [{"text": "해야 할 일", "source_text": "해야 할 일"}],
            "people": [{"mention": "김대리", "role_hint": None, "source_text": "김대리"}],
            "time": [
                {
                    "mention": "이번 주",
                    "granularity_hint": "RELATIVE",
                    "source_text": "이번 주",
                }
            ],
            "sources": [
                {"source": "GMAIL", "mention": "메일", "confidence": "HIGH"},
                {"source": "TASKS", "mention": "해야 할 일", "confidence": "MEDIUM"},
            ],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {
            "is_unsupported": False,
            "reason_code": None,
            "explanation": None,
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD", "TASK"],
        "analysis_requirement": "REQUIRED",
    }


def _clear_intent() -> dict[str, object]:
    return _base_intent()


def _ambiguous_intent() -> dict[str, object]:
    intent = _base_intent()
    intent["goal"] = {
        "summary": "그 사람과 이야기했던 일정 정리",
        "user_visible_objective": "그 사람과 이야기했던 일정 정리",
    }
    intent["semantic_constraints"] = {
        **cast(dict[str, object], intent["semantic_constraints"]),
        "people": [{"mention": "그 사람", "role_hint": None, "source_text": "그 사람"}],
        "sources": [{"source": "CALENDAR", "mention": "일정", "confidence": "HIGH"}],
    }
    intent["ambiguity"] = {
        "is_ambiguous": True,
        "items": [
            {
                "field_path": "semantic_constraints.people[0]",
                "reason_code": "INTENT_AMBIGUITY_MISSED",
                "user_question": "어떤 사람을 말하는지 알려주세요.",
            }
        ],
    }
    return intent


def _minsu_intent() -> dict[str, object]:
    intent = _base_intent()
    intent["goal"] = {
        "summary": "민수와 이야기했던 일정 정리",
        "user_visible_objective": "민수와 이야기했던 일정 정리",
    }
    intent["semantic_constraints"] = {
        **cast(dict[str, object], intent["semantic_constraints"]),
        "people": [{"mention": "민수", "role_hint": None, "source_text": "민수"}],
        "sources": [{"source": "CALENDAR", "mention": "일정", "confidence": "HIGH"}],
    }
    return intent


def _unsupported_intent() -> dict[str, object]:
    intent = _base_intent()
    intent["goal"] = {
        "summary": "메일 삭제",
        "user_visible_objective": "메일 삭제",
    }
    intent["completion_criteria"] = ["메일 삭제 완료"]
    intent["semantic_constraints"] = {
        **cast(dict[str, object], intent["semantic_constraints"]),
        "topics": [{"text": "삭제", "source_text": "삭제"}],
        "negative_constraints": [],
        "policy_or_safety_constraints": ["Gmail 삭제는 제품 범위 제외"],
    }
    intent["unsupported_scope"] = {
        "is_unsupported": True,
        "reason_code": "INTENT_UNSUPPORTED_SCOPE",
        "explanation": "삭제 요청은 현재 제품 범위에서 처리할 수 없습니다.",
    }
    return intent
