from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    _validate_ambiguity,
    detect_ambiguity,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_detect_ambiguity__canonical_call__owns_independent_ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="일정을 잡아줘",
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "일정 만들기",
        "completion_conditions": ["일정을 만든다"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "REQUIRED",
    }
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.detect_ambiguity",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="detect_ambiguity",
        node_state="INITIAL",
        purpose="detect_ambiguity",
        input_schema_version="v1",
        output_schema_version="v1",
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=prompt_ref,
    )

    assert result["requires_confirmation"] is True
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "일정을 잡아줘",
        "goal_candidate": candidate,
        "selected_resource_refs": [],
    }


def test_detect_ambiguity__rejects_metadata__without_confirmation() -> None:
    with pytest.raises(ValueError, match="non-confirmation ambiguity metadata must be empty"):
        _validate_ambiguity(
            {
                "requires_confirmation": False,
                "missing_information_owner": "NONE",
                "reason_codes": ["MISSING_PROJECT_NAME"],
                "missing_fields": ["project_name"],
            }
        )


def test_selected_gmail_read__with_retrievable_content_gap__does_not_confirm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
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
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 메일 읽기",
        "completion_conditions": ["메일 내용을 요약한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="request_understanding.detect_ambiguity",
            prompt_version="1",
            content_hash="hash",
            agent_role="request_understanding",
            subgraph_name="request_understanding",
            node_name="detect_ambiguity",
            node_state="INITIAL",
            purpose="detect_ambiguity",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_general_advice__does_not_ask_for_model_invented_user_choice() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    request = _answer_only_request("프로젝트 회의 준비 원칙을 한 문장으로 알려줘.")
    candidate: RequestGoalCandidateV1 = {
        "goal": "프로젝트 회의 준비 원칙 제공",
        "completion_conditions": ["한 문장으로 원칙을 답한다"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="request_understanding.detect_ambiguity",
            prompt_version="1",
            content_hash="hash",
            agent_role="request_understanding",
            subgraph_name="request_understanding",
            node_name="detect_ambiguity",
            node_state="INITIAL",
            purpose="detect_ambiguity",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )

    assert result == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert runtime.calls == []


def test_selected_gmail_analysis__detects_user_owned__ambiguity() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["MISSING_ANALYSIS_FOCUS"],
                "missing_fields": ["analysis_focus"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 분석해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate={
            "goal": "선택한 메일 분석",
            "completion_conditions": ["사용자가 선택한 관점으로 메일을 분석한다"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "REQUIRED",
        },
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="request_understanding.detect_ambiguity",
            prompt_version="1",
            content_hash="hash",
            agent_role="request_understanding",
            subgraph_name="request_understanding",
            node_name="detect_ambiguity",
            node_state="INITIAL",
            purpose="detect_ambiguity",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )

    assert result == {
        "requires_confirmation": True,
        "reason_codes": ["MISSING_ANALYSIS_FOCUS"],
        "missing_fields": ["analysis_focus"],
    }
    assert len(runtime.calls) == 1


def test_selected_gmail_send__with_missing_recipient__preserves_confirmation() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "requires_confirmation": True,
                "missing_information_owner": "USER",
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            }
        ]
    )
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="이 메일에 답장해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    candidate: RequestGoalCandidateV1 = {
        "goal": "선택한 메일에 답장",
        "completion_conditions": ["답장을 보낸다"],
        "constraints": [],
        "requested_effect_hints": ["READ", "SEND"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=PromptReference(
            prompt_bundle_version="test",
            prompt_id="request_understanding.detect_ambiguity",
            prompt_version="1",
            content_hash="hash",
            agent_role="request_understanding",
            subgraph_name="request_understanding",
            node_name="detect_ambiguity",
            node_state="INITIAL",
            purpose="detect_ambiguity",
            input_schema_version="v1",
            output_schema_version="v1",
        ),
    )

    assert result["requires_confirmation"] is True
    assert result["missing_fields"] == ["recipient"]


def _answer_only_request(text: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-answer",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text=text,
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
