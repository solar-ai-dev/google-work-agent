from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_identify_goal__canonical_call__uses_bounded_current_run_prompt() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "업무 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": [],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )
    request = _request("관련 메일을 찾아줘")
    prompt_ref = _prompt_ref("request_understanding.identify_goal", "identify_goal")

    candidate = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)

    assert candidate["goal"] == "업무 메일 찾기"
    assert "ambiguity" not in candidate
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "관련 메일을 찾아줘",
        "selected_resource_refs": [],
    }
    prompt = cast(PromptReference, runtime.calls[0]["prompt_ref"])
    assert prompt.prompt_id == "request_understanding.identify_goal"


def test_identify_goal__selected_resource__preserves_trusted_read_identity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "선택한 메일 요약",
                "completion_conditions": ["요약을 답한다"],
                "constraints": [],
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 읽고 요약해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["constraints"] == [
        {
            "kind": "RESOURCE",
            "field": "selected_resource_id",
            "value": ["thread-42"],
        }
    ]


def test_identify_goal__workspace_effect_without_resource_hint__fails_contract() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "캘린더 일정 생성",
                "completion_conditions": ["일정이 생성된다"],
                "constraints": [],
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("내 캘린더에 일정을 만들어줘"),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )


def test_identify_goal__answer_only__allows_empty_workspace_hints() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "간단한 답변",
                "completion_conditions": ["답을 표시한다"],
                "constraints": [],
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("2 더하기 2는?"),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == []
    assert candidate["requested_resource_hints"] == []


def test_identify_goal__explicit_google_tasks_read__preserves_deterministic_hints() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "현재 할 일 목록 제공",
                "completion_conditions": ["할 일을 간단히 답한다"],
                "constraints": [],
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("Google Tasks에 있는 현재 할 일을 목록으로 간단히 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["TASK"]


def _request(text: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=text,
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )


def _prompt_ref(prompt_id: str, node_name: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name=node_name,
        node_state="INITIAL",
        purpose=node_name,
        input_schema_version="v1",
        output_schema_version="v1",
    )
