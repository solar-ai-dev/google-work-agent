from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections import (
    request_confirmation_projection,
)


def test_korean_request_confirmation__uses_user_language_and_hides_reason_code() -> None:
    question = request_confirmation_projection.build_request_clarification_question(
        request_text="회의 일정을 만들어줘",
        ambiguity={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_START_TIME"],
            "missing_fields": ["start_time"],
        },
        goal_candidate={
            "goal": "회의 일정 만들기",
            "completion_conditions": ["일정이 생성된다"],
            "constraints": [],
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["CALENDAR_EVENT"],
            "analysis_requirement": "NONE",
        },
    )

    assert question["question"] == "요청을 진행하려면 다음 정보를 알려주세요: 시작 시간."
    assert "MISSING_START_TIME" not in question["question"]
    assert question["reason_code"] == "MISSING_START_TIME"


def test_korean_request_confirmation__does_not_expose_unknown_internal_field() -> None:
    question = request_confirmation_projection.build_request_clarification_question(
        request_text="업무를 처리해줘",
        ambiguity={
            "requires_confirmation": True,
            "reason_codes": ["MISSING_INTERNAL_VALUE"],
            "missing_fields": ["$.internal_value"],
        },
        goal_candidate={
            "goal": "업무 처리",
            "completion_conditions": ["업무가 완료된다"],
            "constraints": [],
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
    )

    assert question["question"] == (
        "요청을 진행하는 데 필요한 선택 사항이 있습니다. "
        "원하는 내용을 조금 더 구체적으로 알려주세요."
    )
    assert "internal_value" not in question["question"]
