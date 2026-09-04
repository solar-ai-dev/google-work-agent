from google_work_agent.application.agents.planning.project_task_read_answer import (
    project_task_read_answer,
)


def test_task_read_answer__lists_concrete_task_evidence_in_user_language() -> None:
    result = project_task_read_answer(
        user_request="Google Tasks의 현재 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:42",
                "excerpt": "[GWA LIVE SMOKE] Task 20260903-3F7A9C2D",
            },
            {
                "evidence_id": "e-list",
                "resource_handle": "task_list:default",
                "excerpt": "내 할 일 목록",
            },
        ],
    )

    assert result is not None
    assert result.outline == {
        "sections": ["현재 Google Tasks 할 일"],
        "evidence_refs": ["e-task"],
    }
    assert result.draft == {
        "schema_version": 2,
        "answer": (
            "Google Tasks에서 확인된 현재 할 일은 1개입니다.\n\n"
            "- [GWA LIVE SMOKE] Task 20260903-3F7A9C2D"
        ),
        "evidence_refs": ["e-task"],
    }


def test_task_read_answer__does_not_replace_analytical_or_mixed_resource_answers() -> None:
    assert (
        project_task_read_answer(
            user_request="태스크를 분석해줘.",
            request_intent={
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["TASK"],
                "analysis_requirement": "REQUIRED",
            },
            evidence=[],
        )
        is None
    )
