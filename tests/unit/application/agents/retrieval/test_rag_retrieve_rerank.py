from typing import cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank


def test_rag_ranking_is_deterministic_and_prompt_free() -> None:
    intent = cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "i", "revision": 1, "based_on": []},
            "goal": "alpha",
            "constraints": [],
            "requested_effect_hints": ["READ"],
        },
    )
    segments = [
        SourceSegment("seg_b", "h2", "GMAIL", "gmail_message", "m2", None, None, {}, "alpha"),
        SourceSegment("seg_a", "h1", "GMAIL", "gmail_message", "m1", None, None, {}, "alpha"),
    ]

    assert [
        item["segment_id"] for item in rag_retrieve_rerank(segments, request_intent=intent, top_k=2)
    ] == ["seg_a", "seg_b"]
