from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.planning.compose_answer import (
    answer_draft_output_schema,
    compose_answer,
)


def test_answer_draft_schema__binds_citations__to_approved_outline() -> None:
    schema = answer_draft_output_schema(["e2", "e1", "e1"])
    properties = schema.json_schema["properties"]

    assert properties["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["e1", "e2"]},
    }
    assert properties["answer"] == {"type": "string", "minLength": 1}


def test_compose_uses__approved_outline_and__emits_v2_candidate() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"schema_version": 2, "answer": "Grounded answer", "evidence_refs": ["e1"]}

    result = compose_answer(
        user_request="Summarize.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["Conclusion"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
        invoke=invoke,
    )

    assert result["schema_version"] == 2
    assert captured["prompt_id"] == "planning.compose_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "answer_outline",
        "evidence",
    }


def test_compose_normalizes__harmless_surrounding_whitespace() -> None:
    result = compose_answer(
        user_request="요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "e1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "\n  확인한 메일을 요약했습니다.  \n",
            "evidence_refs": ["e1"],
        },
    )

    assert result["answer"] == "확인한 메일을 요약했습니다."


def test_compose_removes__internal_evidence_refs_and_reason_codes() -> None:
    result = compose_answer(
        user_request="메일 근거를 요약해줘.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["핵심"], "evidence_refs": ["evidence-seg_deadbeef"]},
        work_analysis=None,
        evidence=[{"evidence_id": "evidence-seg_deadbeef"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": (
                "evidence-seg_deadbeef에서 REQUIRED_SOURCE_RETURNED_NO_RESOURCES를 확인했습니다."
            ),
            "evidence_refs": ["evidence-seg_deadbeef"],
        },
    )

    assert result["answer"] == "확인한 자료에서 내부 상태를 확인했습니다."


def test_compose_internal_reference_labels__preserve_english_request_language() -> None:
    result = compose_answer(
        user_request="Summarize the email evidence.",
        request_intent={"goal": "summary"},
        answer_outline={"sections": ["Summary"], "evidence_refs": ["evidence-seg_1"]},
        work_analysis=None,
        evidence=[{"evidence_id": "evidence-seg_1"}],
        invoke=lambda _prompt_id, _prompt_input: {
            "schema_version": 2,
            "answer": "evidence-seg_1 has REQUIRED_SOURCE_EVIDENCE.",
            "evidence_refs": ["evidence-seg_1"],
        },
    )

    assert result["answer"] == "the reviewed material has an internal status."


def test_compose_empty_gmail_read__explains_search_result_without_llm() -> None:
    invoked = False

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {}

    result = compose_answer(
        user_request="지난주 프로젝트 일정 메일을 찾아줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "constraints": [
                {"kind": "DATE", "field": "period", "value": ["지난주"]},
                {
                    "kind": "USER_REQUIREMENT",
                    "field": "search_terms",
                    "value": ["프로젝트", "일정"],
                },
            ],
        },
        answer_outline={"sections": ["검색 결과 없음"], "evidence_refs": []},
        work_analysis=None,
        evidence=[],
        retrieval_result={
            "coverage": "PARTIAL",
            "source_statuses": [{"status": "COMPLETE", "failure_kind": None}],
            "missing_information": [{"description": "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"}],
        },
        invoke=invoke,
    )

    assert invoked is False
    assert result["answer"] == (
        "'지난주 · 프로젝트 · 일정' 조건으로 Gmail을 검색했지만 관련 자료를 찾지 "
        "못했습니다. 검색어나 기간을 넓혀 다시 요청해 주세요."
    )


def test_compose_rejects__evidence_not__approved_by_outline() -> None:
    with pytest.raises(ValueError, match="outside"):
        compose_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["Conclusion"], "evidence_refs": []},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "schema_version": 2,
                "answer": "Unsupported",
                "evidence_refs": ["e1"],
            },
        )


def test_compose_rejects__serialized_internal_object__as_user_answer() -> None:
    with pytest.raises(ValueError, match="user-visible prose"):
        compose_answer(
            user_request="요약해줘.",
            request_intent={"goal": "summary"},
            answer_outline={"sections": ["핵심"], "evidence_refs": ["e1"]},
            work_analysis=None,
            evidence=[{"evidence_id": "e1"}],
            invoke=lambda _prompt_id, _prompt_input: {
                "schema_version": 2,
                "answer": '  {"sections":[],"evidence_refs":["e1"]}',
                "evidence_refs": ["e1"],
            },
        )


def test_compose_task_read__uses_grounded_projection_without_llm() -> None:
    invoked = False

    def invoke(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal invoked
        invoked = True
        return {}

    result = compose_answer(
        user_request="Google Tasks 할 일을 목록으로 알려줘.",
        request_intent={
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "NONE",
        },
        answer_outline={"sections": ["현재 Google Tasks 할 일"], "evidence_refs": ["e1"]},
        work_analysis=None,
        evidence=[
            {
                "evidence_id": "e1",
                "resource_handle": "task:1",
                "excerpt": "보고서 제출",
            }
        ],
        invoke=invoke,
    )

    assert invoked is False
    assert result["answer"].endswith("- 보고서 제출")
