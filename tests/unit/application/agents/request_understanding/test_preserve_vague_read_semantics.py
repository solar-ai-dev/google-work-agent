from google_work_agent.application.agents.request_understanding import (
    preserve_vague_read_semantics as operation,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)


def _candidate() -> RequestGoalCandidateV1:
    return {
        "goal": "Find and analyze meeting email",
        "completion_conditions": ["Provide schedule"],
        "constraints": [
            {"kind": "DATE", "field": "start", "value": "N/A"},
            {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
        ],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def test_vague_read_semantics__restores_search_meaning_and_removes_placeholder() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert "start" not in by_field
    assert by_field["timezone"] == "Asia/Seoul"
    assert by_field["original_search_request"] == [
        "회의 관련 메일이 있는데 그거 분석해서 일정 정리해줘."
    ]
    assert by_field["search_terms"] == ["회의"]
    assert by_field["required_information"] == ["일정"]


def test_vague_read_semantics__preserves_people_periods_and_business_topics() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="지난주에 김대리와 이야기했던 프로젝트 일정 메일을 찾아봐.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["person"] == ["김대리"]
    assert by_field["period"] == ["지난주"]
    assert by_field["search_terms"] == ["일정"]


def test_vague_read_semantics__does_not_use_discussion_verbs_as_search_terms() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="지난주에 프로젝트 일정 얘기한 메일 찾아서 해야 할 일 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["period"] == ["지난주"]
    assert by_field["search_terms"] == ["프로젝트", "일정"]


def test_explicit_gmail_subject__replaces_broad_search_terms_with_exact_literal() -> None:
    request_text = (
        "Gmail에서 제목이 '절대로 존재하지 않는 3/8 검증 메일 20260905'인 "
        "메일을 찾아 분석해줘."
    )
    candidate = _candidate()
    candidate["constraints"] = [
        {
            "kind": "RESOURCE",
            "field": "search_terms",
            "value": "제목:절대로 존재하지 않는 3/8 검증 메일 20260905",
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["검증"]},
    ]
    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text=request_text,
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["subject"] == ["절대로 존재하지 않는 3/8 검증 메일 20260905"]
    assert "search_terms" not in by_field


def test_vague_read_semantics__replaces_model_broad_query_with_source_terms() -> None:
    candidate = _candidate()
    candidate["constraints"].append(
        {
            "kind": "USER_REQUIREMENT",
            "field": "search_terms",
            "value": ["최근 회의 메일"],
        }
    )

    result = operation.preserve_vague_read_semantics(
        candidate,
        request_text="최근 회의 메일 중 아직 후속 작업이 안 된 내용을 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["search_terms"] == ["회의"]
    assert by_field["period"] == ["최근"]


def test_vague_read_semantics__preserves_answer_information_without_making_it_query_text() -> None:
    result = operation.preserve_vague_read_semantics(
        _candidate(),
        request_text="최근 회의 메일 중 아직 후속 작업이 안 된 내용과 최신 결정을 정리해줘.",
        entry_mode="AGENT_SEARCH",
    )

    by_field = {constraint["field"]: constraint["value"] for constraint in result["constraints"]}
    assert by_field["period"] == ["최근"]
    assert by_field["search_terms"] == ["회의"]
    assert by_field["required_information"] == ["후속 작업", "최신 결정"]
