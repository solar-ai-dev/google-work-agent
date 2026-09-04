from google_work_agent.application.agents.planning.project_gmail_security_read_answer import (
    project_gmail_security_read_answer,
)


def test_selected_security_alert__with_device_and_date__projects_exact_facts() -> None:
    result = project_gmail_security_read_answer(
        user_request="선택한 메일의 로그인 기기와 날짜를 한국어로 알려줘.",
        request_intent={
            "analysis_requirement": "NONE",
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {"kind": "RESOURCE", "field": "resource_id", "value": "thread-1"}
            ],
        },
        evidence=[
            {
                "evidence_id": "e1",
                "excerpt": (
                    "보안 알림 Windows에서 새로 로그인함 "
                    "Date: Fri, 04 Sep 2026 07:30:31 GMT Subject: 보안 알림"
                ),
            }
        ],
    )

    assert result is not None
    assert result.draft == {
        "schema_version": 2,
        "answer": (
            "선택한 메일에서 확인된 로그인 기기는 Windows이며, "
            "알림 날짜는 2026년 9월 4일 07:30:31 GMT입니다."
        ),
        "evidence_refs": ["e1"],
    }


def test_unselected_security_search__with_same_words__keeps_general_planning() -> None:
    assert (
        project_gmail_security_read_answer(
            user_request="로그인 기기와 날짜를 알려줘.",
            request_intent={
                "analysis_requirement": "NONE",
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "constraints": [],
            },
            evidence=[],
        )
        is None
    )
