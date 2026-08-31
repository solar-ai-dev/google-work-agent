from collections import deque
from dataclasses import replace
from typing import cast

from tests.unit.application.workflows.test_context_retrieval import (
    SELECT_PROMPT_REF,
    FakeLLMRuntime,
    _intent,
    _llm_result,
    _run_budget,
)

from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.agents.retrieval.select_evidence import select_evidence


def test_select_evidence_preserves_stable_exclusion_obligations() -> None:
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
