from __future__ import annotations

from typing import Any, cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@pytest.mark.parametrize("request_text, expected_resources", [
    (
        "Google Calendar에 'Gmail Google Tasks 검증' 일정을 만들어줘. "
        "설명은 '메일을 읽어줘'이고 참석자는 reviewer@gmail.com이야.",
        ["CALENDAR_EVENT"],
    ),
    (
        "reviewer@gmail.com의 메일을 찾아서 Google Calendar에 일정을 만들어줘.",
        ["CALENDAR_EVENT", "GMAIL_THREAD"],
    ),
])
def test_identify_goal__payload_literals_do_not__add_unrequested_resources(
    request_text: str, expected_resources: list[str],
) -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "일정 생성", "completion_conditions": ["일정을 생성한다"],
        "constraints": [{"kind": "RESOURCE", "field": "title", "value": "검증"}],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "NONE",
    }])
    candidate = identify_goal(
        llm_runtime=runtime, request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert candidate["requested_resource_hints"] == expected_resources
    assert candidate["requested_effect_hints"] == ["CREATE"]


def test_identify_goal__preserves_exact_quoted__description_spacing() -> None:
    runtime = FakeStructuredInferencePort(outputs=[{
        "goal": "일정 생성", "completion_conditions": ["일정을 생성한다"],
        "constraints": [{
            "kind": "RESOURCE", "field": "description",
            "value": "Task 와 Calendar 검증 결과를 확인합니다.",
        }],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"], "analysis_requirement": "NONE",
    }])
    result = identify_goal(
        llm_runtime=runtime,
        request=_request("일정을 만들어줘. 설명은 'Task와 Calendar 검증 결과를 확인합니다.'야."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )
    assert result["constraints"][0]["value"] == "Task와 Calendar 검증 결과를 확인합니다."


def test_identify_goal__canonical_call__uses_bounded_current_run_prompt() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "업무 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": [
                    {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": "관련"}
                ],
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
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert cast(dict[str, Any], output_schema.json_schema["properties"])["constraints"][
        "minItems"
    ] == 1


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
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD"]
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


def test_identify_goal__general_advice__removes_model_invented_workspace_reads() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "프로젝트 회의 준비 원칙 제공",
                "completion_conditions": ["한 문장으로 원칙을 답한다"],
                "constraints": [],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD", "TASK", "CALENDAR_EVENT"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("프로젝트 회의 준비 원칙을 한 문장으로 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == []
    assert candidate["requested_resource_hints"] == []
    assert candidate["analysis_requirement"] == "NONE"


def test_identify_goal__current_workspace_read__is_not_rewritten_as_advice() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "현재 Google Tasks 원칙 확인",
                "completion_conditions": ["현재 태스크를 읽어 답한다"],
                "constraints": [
                    {"kind": "SCOPE", "field": "status", "value": "현재"}
                ],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("내 Google Tasks의 현재 우선순위 원칙을 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["TASK"]


def test_identify_goal__explicit_google_tasks_read__preserves_deterministic_hints() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "현재 할 일 목록 제공",
                "completion_conditions": ["할 일을 간단히 답한다"],
                "constraints": [
                    {"kind": "SCOPE", "field": "status", "value": "현재"}
                ],
                "requested_effect_hints": [],
                "requested_resource_hints": ["TASK"],
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
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert "allOf" not in output_schema.json_schema


def test_identify_goal__vague_mail_read__requires_original_search_semantics() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "회의 관련 메일을 분석해 일정 정리",
                "completion_conditions": ["회의 일정 근거를 정리한다"],
                "constraints": [
                    {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": "회의"},
                    {
                        "kind": "USER_REQUIREMENT",
                        "field": "required_information",
                        "value": ["일정", "후속 작업"],
                    },
                ],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "REQUIRED",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["constraints"][0] == {
        "kind": "USER_REQUIREMENT",
        "field": "search_terms",
        "value": "회의",
    }
    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert cast(dict[str, Any], output_schema.json_schema["properties"])["constraints"][
        "minItems"
    ] == 1


def test_identify_goal__restores_vague_search_semantics_omitted_by_inference() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "Find and analyze meeting-related emails",
                "completion_conditions": ["Summarize schedule information"],
                "constraints": [
                    {"kind": "DATE", "field": "start", "value": "N/A"},
                    {"kind": "DATE", "field": "end", "value": "N/A"},
                    {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
                ],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )
    request_text = "회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    by_field = {item["field"]: item["value"] for item in candidate["constraints"]}
    assert "start" not in by_field
    assert "end" not in by_field
    assert by_field["original_search_request"] == [request_text]
    assert by_field["search_terms"] == ["회의"]
    assert by_field["required_information"] == ["일정"]
    assert candidate["analysis_requirement"] == "REQUIRED"


def test_identify_goal__latest_decision_read__requires_analysis() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "KAN-93 관련 메일 찾기",
                "completion_conditions": ["관련 메일을 찾는다"],
                "constraints": [
                    {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": "KAN-93"}
                ],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("KAN-93 관련 메일이 여러 개일 때 최신 결정이 무엇인지 알려줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["analysis_requirement"] == "REQUIRED"


def test_identify_goal__vague_mail_schedule_summary__rejects_invented_calendar_create() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "회의 메일을 분석하고 캘린더 일정을 만든다",
                "completion_conditions": ["회의 일정을 생성한다"],
                "constraints": [
                    {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": "회의"}
                ],
                "requested_effect_hints": ["READ", "CREATE"],
                "requested_resource_hints": ["GMAIL_THREAD", "CALENDAR_EVENT"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request("회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert candidate["requested_effect_hints"] == ["READ"]
    assert candidate["requested_resource_hints"] == ["GMAIL_THREAD"]
    assert candidate["analysis_requirement"] == "REQUIRED"


def test_identify_goal__explicit_google_tasks_write__does_not_infer_read() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": [],
                "requested_effect_hints": [],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        ]
    )

    with pytest.raises(ValueError, match="request goal candidate is invalid"):
        identify_goal(
            llm_runtime=runtime,
            request=_request("Google Tasks 목록에 새 할 일을 만들어줘."),
            prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
        )

    output_schema = cast(OutputSchemaDefinition, runtime.calls[0]["output_schema"])
    assert "allOf" in output_schema.json_schema


@pytest.mark.parametrize(
    ("request_text", "expected_dates"),
    [
        (
            "Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 만들어줘.",
            [],
        ),
        (
            "Google Tasks에 '2/8 Supervisor 승인 테스트' 태스크를 2026-09-05까지 만들어줘.",
            ["2026-09-05"],
        ),
    ],
)
def test_identify_goal__quoted_task_title__does_not_become_an_unstated_date(
    request_text: str,
    expected_dates: list[str],
) -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "goal": "새 할 일 생성",
                "completion_conditions": ["할 일을 생성한다"],
                "constraints": [
                    {"kind": "DATE", "field": "date", "value": "2026-02-08"},
                    {
                        "kind": "RESOURCE",
                        "field": "title",
                        "value": "2/8 Supervisor 승인 테스트",
                    },
                ]
                + (
                    [{"kind": "DATE", "field": "due", "value": "2026-09-05"}]
                    if expected_dates
                    else []
                ),
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "NONE",
            }
        ]
    )

    candidate = identify_goal(
        llm_runtime=runtime,
        request=_request(request_text),
        prompt_ref=_prompt_ref("request_understanding.identify_goal", "identify_goal"),
    )

    assert [
        constraint["value"]
        for constraint in candidate["constraints"]
        if constraint["kind"] == "DATE"
    ] == expected_dates


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
