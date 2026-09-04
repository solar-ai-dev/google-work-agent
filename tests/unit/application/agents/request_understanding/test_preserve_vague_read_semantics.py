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
