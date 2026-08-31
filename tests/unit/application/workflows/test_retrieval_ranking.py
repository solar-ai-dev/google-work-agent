"""Tests for retrieval.rag_retrieve deterministic scoring/ranking
(docs/05-context-retrieval.md SS5.5)."""

from __future__ import annotations

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.context_segmentation import _SourceSegment
from google_work_agent.application.orchestration.retrieval_ranking import (
    EXACT_RESOURCE_REASON,
    KEYWORD_MATCH_REASON,
    RELATED_RESOURCE_REASON,
    RESOURCE_SELECTED_FORCED_REASON,
    RagScoringConfig,
    rank_segments,
)


def _segment(
    *,
    segment_id: str,
    resource_id: str,
    parent_id: str | None = None,
    text: str = "",
) -> _SourceSegment:
    return _SourceSegment(
        segment_id=segment_id,
        resource_handle=f"gmail_thread:{resource_id}",
        source="GMAIL",
        resource_type="gmail_thread",
        resource_id=resource_id,
        parent_id=parent_id,
        version="1",
        locator={"kind": "resource_payload", "position": 0, "chunk_index": 0, "chunk_count": 1},
        text=text,
    )


def _intent(
    *,
    goal: str = "",
    selected_resource_ids: list[str] | None = None,
) -> RequestIntentV2:
    constraints: list[ConstraintV1] = []
    if selected_resource_ids:
        constraints.append(
            {
                "kind": "RESOURCE",
                "field": "selected_resource_ids",
                "value": selected_resource_ids,
            }
        )
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": goal,
        "completion_conditions": [],
        "constraints": constraints,
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def test_determinism_same_input_produces_same_scores_and_order() -> None:
    segments = [
        _segment(segment_id="seg-1", resource_id="thread-a", text="project follow-up meeting"),
        _segment(segment_id="seg-2", resource_id="thread-b", text="unrelated lunch order"),
    ]
    intent = _intent(goal="project follow-up meeting")

    first = rank_segments(segments, request_intent=intent, top_k=10)
    second = rank_segments(list(reversed(segments)), request_intent=intent, top_k=10)

    assert first == second


def test_lexical_relevance_ranks_matching_segment_above_unrelated_one() -> None:
    relevant = _segment(
        segment_id="seg-1", resource_id="thread-a", text="project follow-up meeting notes"
    )
    unrelated = _segment(
        segment_id="seg-2", resource_id="thread-b", text="unrelated lunch order confirmation"
    )
    intent = _intent(goal="project follow-up meeting")

    candidates = rank_segments([unrelated, relevant], request_intent=intent, top_k=10)

    assert [c["segment_id"] for c in candidates][0] == "seg-1"
    assert candidates[0]["retrieval_score"] > candidates[1]["retrieval_score"]
    assert KEYWORD_MATCH_REASON in candidates[0]["reason_codes"]


def test_exact_resource_match_scores_highest_and_is_labeled() -> None:
    exact = _segment(segment_id="seg-1", resource_id="thread-selected", text="unrelated text")
    other = _segment(
        segment_id="seg-2", resource_id="thread-other", text="project follow-up meeting"
    )
    intent = _intent(goal="project follow-up meeting", selected_resource_ids=["thread-selected"])

    candidates = {
        c["segment_id"]: c for c in rank_segments([exact, other], request_intent=intent, top_k=10)
    }

    assert EXACT_RESOURCE_REASON in candidates["seg-1"]["reason_codes"]
    assert candidates["seg-1"]["retrieval_score"] == RagScoringConfig().exact_resource_score
    assert candidates["seg-1"]["retrieval_score"] > candidates["seg-2"]["retrieval_score"]


def test_related_resource_child_segment_scores_via_parent_link() -> None:
    message = _segment(
        segment_id="seg-2", resource_id="message-1", parent_id="thread-selected", text="reply"
    )
    intent = _intent(selected_resource_ids=["thread-selected"])

    candidates = rank_segments([message], request_intent=intent, top_k=10)

    assert RELATED_RESOURCE_REASON in candidates[0]["reason_codes"]
    assert candidates[0]["retrieval_score"] == RagScoringConfig().related_resource_score


def test_resource_selected_segments_are_never_dropped_by_budget() -> None:
    """docs/05-context-retrieval.md section 7 (RESOURCE_SELECTED): the user's
    explicitly selected resources are force-included regardless of score, so
    a tight top_k must not silently drop one."""
    selected = [
        _segment(segment_id=f"seg-sel-{i}", resource_id=f"thread-{i}", text="irrelevant")
        for i in range(3)
    ]
    intent = _intent(selected_resource_ids=[f"thread-{i}" for i in range(3)])

    candidates = rank_segments(selected, request_intent=intent, top_k=2)

    ids = {c["segment_id"] for c in candidates}
    assert ids == {"seg-sel-0", "seg-sel-1", "seg-sel-2"}
    forced_count = sum(
        1 for c in candidates if RESOURCE_SELECTED_FORCED_REASON in c["reason_codes"]
    )
    assert forced_count == 1


def test_budget_bounds_result_to_top_k_when_no_resource_is_selected() -> None:
    segments = [
        _segment(segment_id=f"seg-{i}", resource_id=f"thread-{i}", text="project follow-up")
        for i in range(10)
    ]
    intent = _intent(goal="project follow-up")

    candidates = rank_segments(segments, request_intent=intent, top_k=3)

    assert len(candidates) == 3


def test_no_query_terms_or_resource_match_scores_zero_with_no_reason_codes() -> None:
    segment = _segment(segment_id="seg-1", resource_id="thread-a", text="")
    intent = _intent(goal="")

    candidates = rank_segments([segment], request_intent=intent, top_k=10)

    assert candidates[0]["retrieval_score"] == 0.0
    assert candidates[0]["reason_codes"] == []


def test_duplicate_segment_id_is_deduplicated() -> None:
    segments = [
        _segment(segment_id="seg-1", resource_id="thread-a", text="duplicate"),
        _segment(segment_id="seg-1", resource_id="thread-a", text="duplicate"),
    ]
    intent = _intent(goal="")

    candidates = rank_segments(segments, request_intent=intent, top_k=10)

    assert len(candidates) == 1
