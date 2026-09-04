from google_work_agent.application.agents.retrieval.has_explicit_gmail_subject import (
    has_explicit_gmail_subject,
)


def test_vague_topic__does_not_promote_inferred_subject_to_exact() -> None:
    assert not has_explicit_gmail_subject(
        [
            {"kind": "RESOURCE", "field": "subject", "value": "project_schedule"},
            {
                "kind": "USER_REQUIREMENT",
                "field": "original_search_request",
                "value": ["지난주 프로젝트 일정 얘기한 메일을 찾아봐"],
            },
        ]
    )


def test_user_named_subject__retains_exact_subject_semantics() -> None:
    assert has_explicit_gmail_subject(
        [
            {"kind": "SCOPE", "field": "search_criteria_subject", "value": "보안 알림"},
            {
                "kind": "USER_REQUIREMENT",
                "field": "original_search_request",
                "value": ["제목이 '보안 알림'인 메일을 찾아줘"],
            },
        ]
    )
