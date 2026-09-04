from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.planning.outline_answer import (
    answer_outline_output_schema,
    outline_answer,
)


def test_answer_outline_schema__binds_citations__to_current_evidence() -> None:
    schema = answer_outline_output_schema(["e2", "e1", "e1"])
    answer_schema = schema.json_schema["oneOf"][0]

    assert answer_schema["properties"]["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }


def test_outline_uses__distinct_prompt__and_minimum_projection() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}

    result = outline_answer(
        user_request="Summarize the current facts.",
        request_intent={"goal": "summary"},
        work_analysis={"action_necessity": "NOT_REQUIRED"},
        evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
        invoke=invoke,
    )

    assert result == {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}
    assert captured["prompt_id"] == "planning.outline_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "work_analysis",
        "evidence",
    }


def test_outline_rejects__evidence_outside__current_projection() -> None:
    with pytest.raises(ValueError, match="outside"):
        outline_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            work_analysis=None,
            evidence=[],
            invoke=lambda _prompt_id, _prompt_input: {
                "sections": ["Conclusion"],
                "evidence_refs": ["previous-run"],
            },
        )


def test_outline__does_not_replace__invalid_evidence_identity() -> None:
    with pytest.raises(ValueError, match="outside"):
        outline_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            work_analysis=None,
            evidence=[{"evidence_id": "evidence-only", "excerpt": "fact"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "sections": ["Conclusion"],
                "evidence_refs": ["invented-reference"],
            },
        )


def test_outline_task_read__selects_concrete_task_without_llm() -> None:
    invoked = False

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {}

    result = outline_answer(
        user_request="Google Tasks 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e-task",
                "resource_handle": "task:1",
                "excerpt": "보고서 제출",
            },
            {
                "evidence_id": "e-list",
                "resource_handle": "task_list:default",
                "excerpt": "내 할 일 목록",
            },
        ],
        invoke=invoke,
    )

    assert invoked is False
    assert result == {
        "sections": ["현재 Google Tasks 할 일"],
        "evidence_refs": ["e-task"],
    }
