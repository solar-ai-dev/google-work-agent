from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import cast

from google_work_agent.application.workflows import (
    RequestUnderstandingAgent,
    RequestUnderstandingResult,
    WorkflowPhase,
)
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


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult | Exception] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: dict[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: object,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
                "output_schema": output_schema,
                "trace_context": trace_context,
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
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
    )

    output = agent.classify(request)
    state_update = agent.build_state_update(output, request=request)

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert output["request_intent"] is not None
    assert output["request_intent"]["schema_version"] == 1
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


def test_linguistically_ambiguous_request_needs_confirmation() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_ambiguous_intent()))
    request = _request("그 사람이랑 얘기했던 일정 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
    )

    output = agent.classify(request)
    state_update = agent.build_state_update(output, request=request)

    assert output["result"] == RequestUnderstandingResult.NEEDS_CONFIRMATION.value
    assert output["request_intent"] is not None
    assert output["clarification"] == {
        "schema_version": 1,
        "question": "어떤 사람을 말하는지 알려주세요.",
        "affected_field_paths": ["semantic_constraints.people[0]"],
        "reason_code": "INTENT_AMBIGUITY_MISSED",
        "known_context_summary": "그 사람과 이야기했던 일정 정리",
    }
    assert output["failure"] is None
    assert state_update["workflow_phase"] == WorkflowPhase.WAITING_CONFIRMATION.value
    assert state_update["user_interrupt"] == output["clarification"]


def test_retrieval_candidate_ambiguity_is_not_confirmed_by_request_understanding() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result(_minsu_intent()))
    request = _request("민수랑 얘기했던 일정 정리해줘.")
    agent = RequestUnderstandingAgent(
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
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
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
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
    assert state_update["user_interrupt"] == output["failure"]


def test_structured_output_schema_error_is_not_converted_to_invalid() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "structured output did not satisfy schema",
        )
    )
    agent = RequestUnderstandingAgent(
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
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
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
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
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
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
        llm_runtime=cast(object, runtime),
        prompt_ref=PROMPT_REF,
    )

    output = agent.classify(_request("김대리 메일 찾아줘."))

    assert output["result"] == RequestUnderstandingResult.COMPLETE.value
    assert len(runtime.calls) == 1


def test_request_understanding_exports_do_not_change_existing_workflow_contracts() -> None:
    from google_work_agent.application import workflows

    assert workflows.RequestUnderstandingResult is RequestUnderstandingResult
    assert workflows.WorkflowPhase is WorkflowPhase
    assert hasattr(workflows, "RequestUnderstandingAgent")
    assert hasattr(workflows, "RequestIntentV1")


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
        "schema_version": 1,
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
