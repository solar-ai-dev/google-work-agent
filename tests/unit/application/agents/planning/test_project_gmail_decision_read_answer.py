from google_work_agent.application.agents.planning.project_gmail_decision_read_answer import (
    project_gmail_decision_read_answer,
)


def test_gmail_decision_read__projects_only_explicitly_decided_source_clauses() -> None:
    result = project_gmail_decision_read_answer(
        user_request="KAN-93 관련 메일이 여러 개일 때 최신 결정이 무엇인지 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "required_information",
                    "value": ["최신 결정"],
                }
            ],
        },
        evidence=[
            {
                "evidence_id": "e-profile",
                "excerpt": (
                    "프로필은 별도 마이페이지가 아니라 이름만 표시하는 방식으로 결정. "
                    "다음 할 일 * [ ] ERD 수정"
                ),
            },
            {
                "evidence_id": "e-navigation",
                "excerpt": (
                    "(오후 12:14 ~) 페이지 이동 방식 후보 * 사이드바 * 네비게이션바 "
                    "→ 네비게이션바로 확정 네비게이션 구성 논의. "
                    "→ 최종 구성 확정 위치 내용 좌측 로고 우측 알림, 설정, "
                    "프로필(이름) 프로필은 별도 마이페이지가 아니라 이름만 표시"
                ),
            },
        ],
    )

    assert result is not None
    assert "프로필은 별도 마이페이지가 아니라 이름만 표시하는 방식으로 결정." in result.draft[
        "answer"
    ]
    assert "페이지 이동 방식 후보 사이드바 네비게이션바 → 네비게이션바로 확정" in result.draft[
        "answer"
    ]
    assert "최종 구성 확정 위치 내용 좌측 로고 우측 알림, 설정, 프로필(이름)" in result.draft[
        "answer"
    ]
    assert "불확실" not in result.draft["answer"]
    assert result.draft["evidence_refs"] == ["e-profile", "e-navigation"]


def test_non_decision_gmail_read__keeps_general_answer_composition() -> None:
    assert (
        project_gmail_decision_read_answer(
            user_request="회의 메일을 요약해줘.",
            request_intent={
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "constraints": [],
            },
            evidence=[{"evidence_id": "e1", "excerpt": "네비게이션바로 확정"}],
        )
        is None
    )
