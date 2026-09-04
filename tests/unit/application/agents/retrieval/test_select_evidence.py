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
    runtime = FakeLLMRuntime(
        deque([_llm_result(container_only), _llm_result(concrete_task)])
    )
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
