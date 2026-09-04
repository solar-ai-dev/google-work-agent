from collections import deque
from dataclasses import replace
from typing import cast

from tests.support.context_retrieval import (
    SELECT_PROMPT_REF,
    FakeLLMRuntime,
    _intent,
    _llm_result,
    _run_budget,
)

from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.agents.retrieval.select_evidence import select_evidence


def test_select_evidence__preserves_stable__exclusion_obligations() -> None:
    runtime = FakeLLMRuntime(
        deque(
            [
                _llm_result(
                    {
                        "schema_version": 2,
                        "evidence_drafts": [
                            {
                                "segment_id": "segment-2",
                                "role": "SUPPORTS",
                                "relevance_reason": "current evidence",
                            }
                        ],
                        "selected_segment_ids": ["segment-2"],
                        "excluded_segment_ids": [],
                    }
                )
            ]
        )
    )
    segments = [
        SourceSegment("segment-1", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "old"),
        SourceSegment("segment-2", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "new"),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": item.segment_id,
            "resource_ref": item.resource_handle,
            "retrieval_score": 1.0,
            "reason_codes": [],
        }
        for item in segments
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=replace(SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence"),
        revision_prompt_ref=replace(
            SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence.revise"
        ),
        requested_mode="AUTO",
        request_intent=_intent(),
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
        exclusion_obligation_segment_ids=["segment-1"],
    )

    assert result["selected_segment_ids"] == ["segment-2"]
    assert result["excluded_segment_ids"] == ["segment-1"]
    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected = cast(list[dict[str, object]], prompt_input["ranked_segments"])
    assert [item["segment_id"] for item in projected] == ["segment-2"]


def test_select_evidence__sole_exact_selected_read__skips_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    intent["constraints"] = [
        {"kind": "RESOURCE", "field": "selected_resource_id", "value": ["thread-42"]}
    ]
    segment = SourceSegment(
        "segment-42",
        "gmail_thread:thread-42",
        "GMAIL",
        "gmail_thread",
        "thread-42",
        None,
        None,
        {},
        "From: sender@example.com\nSubject: request\nPlease reply next week.",
    )

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=[
            {
                "segment_id": segment.segment_id,
                "resource_ref": segment.resource_handle,
                "retrieval_score": 40.0,
                "reason_codes": ["EXACT_RESOURCE"],
            }
        ],
        segments=[segment],
        retry_budget=_run_budget(used=0),
    )

    assert runtime.calls == []
    assert result["selected_segment_ids"] == ["segment-42"]
    assert result["evidence_drafts"][0]["role"] == "SUPPORTS"


def test_select_evidence__repairs_container_only_selection__for_task_read() -> None:
    container_only = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "task-list-segment",
                "role": "CONTEXT",
                "relevance_reason": "Task list container",
            }
        ],
        "selected_segment_ids": ["task-list-segment"],
        "excluded_segment_ids": ["task-segment"],
    }
    concrete_task = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "task-segment",
                "role": "SUPPORTS",
                "relevance_reason": "Concrete requested task",
            }
        ],
        "selected_segment_ids": ["task-segment"],
        "excluded_segment_ids": ["task-list-segment"],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(container_only), _llm_result(concrete_task)]))
    intent = _intent()
    intent["requested_resource_hints"] = ["TASK"]
    segments = [
        SourceSegment(
            "task-list-segment",
            "task_list:list-1",
            "TASKS",
            "task_list",
            "list-1",
            None,
            None,
            {},
            "내 할 일 목록",
        ),
        SourceSegment(
            "task-segment",
            "task:task-1",
            "TASKS",
            "task",
            "task-1",
            "list-1",
            None,
            {},
            "[GWA LIVE SMOKE] Task 20260903-3F7A9C2D",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 1.0,
            "reason_codes": [],
        }
        for segment in segments
    ]

    result, budget = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=replace(
            SELECT_PROMPT_REF, prompt_id="retrieval.select_evidence.revise"
        ),
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"] == ["task-segment"]
    assert len(runtime.calls) == 2
    assert budget["semantic_revisions_used_by_failure"]


def test_select_evidence__promotes_meeting_record_over_notification_for_detail_read() -> None:
    notification_only = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "notification",
                "role": "SUPPORTS",
                "relevance_reason": "mentions a meeting summary",
            }
        ],
        "selected_segment_ids": ["notification"],
        "excluded_segment_ids": ["minutes", "minutes-typo"],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(notification_only)]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["회의 관련 메일을 분석해서 일정 정리해줘"],
        }
    ]
    segments = [
        SourceSegment(
            "notification",
            "gmail_thread:notice",
            "GMAIL",
            "gmail_thread",
            "notice",
            None,
            None,
            {},
            "새 공지: ‘팀별회의 요약’ 알림 설정",
        ),
        SourceSegment(
            "minutes",
            "gmail_thread:minutes",
            "GMAIL",
            "gmail_thread",
            "minutes",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록",
        ),
        SourceSegment(
            "minutes-typo",
            "gmail_thread:minutes-typo",
            "GMAIL",
            "gmail_thread",
            "minutes-typo",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의혹",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 5.0,
            "reason_codes": ["KEYWORD_MATCH"],
        }
        for segment in segments
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"][:2] == ["minutes", "minutes-typo"]
    assert result["evidence_drafts"][0] == {
        "segment_id": "minutes",
        "role": "SUPPORTS",
        "relevance_reason": "CONTENT_BEARING_WORK_RECORD",
    }


def test_select_evidence__preserves_one_candidate_per_explicit_work_lineage() -> None:
    empty_selection = {
        "schema_version": 2,
        "evidence_drafts": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
    }
    runtime = FakeLLMRuntime(
        deque([_llm_result(empty_selection), _llm_result(empty_selection)])
    )
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["KAN-93 관련 메일이 여러 개일 때 최신 결정이 무엇인지 알려줘."],
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["KAN-93"]},
    ]
    segments = [
        SourceSegment(
            "first-body-1",
            "gmail_thread:first",
            "GMAIL",
            "gmail_thread",
            "first",
            None,
            None,
            {},
            "KAN-93 첫 번째 스레드의 상세 본문 1",
        ),
        SourceSegment(
            "first-body-2",
            "gmail_thread:first",
            "GMAIL",
            "gmail_thread",
            "first",
            None,
            None,
            {},
            "KAN-93 첫 번째 스레드의 상세 본문 2",
        ),
        SourceSegment(
            "second-metadata",
            "gmail_thread:second",
            "GMAIL",
            "gmail_thread",
            "second",
            None,
            None,
            {},
            "[Jira] (KAN-93) 후속 회의록",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 10.0 - index,
            "reason_codes": ["KEYWORD_MATCH"],
        }
        for index, segment in enumerate(segments)
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"] == ["second-metadata", "first-body-1"]
    assert len(
        {
            next(
                segment.resource_handle
                for segment in segments
                if segment.segment_id == segment_id
            )
            for segment_id in result["selected_segment_ids"]
        }
    ) == 2


def test_select_evidence__prefers_detail_content_over_same_thread_search_preview() -> None:
    preview_selection = {
        "schema_version": 2,
        "evidence_drafts": [
            {
                "segment_id": "preview",
                "role": "SUPPORTS",
                "relevance_reason": "matching subject",
            },
            {
                "segment_id": "second-preview",
                "role": "SUPPORTS",
                "relevance_reason": "matching subject",
            },
        ],
        "selected_segment_ids": ["preview", "second-preview"],
        "excluded_segment_ids": [],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(preview_selection)]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    intent["constraints"] = [
        {
            "kind": "USER_REQUIREMENT",
            "field": "original_search_request",
            "value": ["KAN-93 관련 메일 중 최신 결정을 알려줘."],
        },
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["KAN-93"]},
    ]
    segments = [
        SourceSegment(
            "preview",
            "gmail_thread:thread-1",
            "GMAIL",
            "gmail_thread",
            "thread-1",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록 최수진 님이 1개 항목을 업데이트했습니다.",
        ),
        SourceSegment(
            "detail",
            "gmail_thread:thread-1",
            "GMAIL",
            "gmail_thread",
            "thread-1",
            None,
            None,
            {},
            "From: 최수진 <jira@example.com>\nDate: 2026-04-22 15:49\n"
            "상태: 해야 할 일 → 진행",
        ),
        SourceSegment(
            "decision-without-lineage-in-chunk",
            "gmail_thread:thread-2",
            "GMAIL",
            "gmail_thread",
            "thread-2",
            None,
            None,
            {},
            "네비게이션바로 확정. 다음 할 일은 와이어프레임 수정이며 담당자는 박희정입니다.",
        ),
        SourceSegment(
            "second-preview",
            "gmail_thread:thread-2",
            "GMAIL",
            "gmail_thread",
            "thread-2",
            None,
            None,
            {},
            "[Jira] (KAN-93) 0422 회의록\nFrom: 최수진\nDate: 2026-04-22\n"
            "담당자: bonggyulim0728\n기한: 2026-04-22",
        ),
    ]
    candidates: list[RagCandidateV1] = [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": 10.0 - index,
            "reason_codes": ["KEYWORD_MATCH"] if "KAN-93" in segment.text else [],
        }
        for index, segment in enumerate(segments)
    ]

    result, _ = select_evidence(
        llm_runtime=runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        rag_candidates=candidates,
        segments=segments,
        retry_budget=_run_budget(used=0),
    )

    assert result["selected_segment_ids"][:2] == [
        "detail",
        "decision-without-lineage-in-chunk",
    ]
