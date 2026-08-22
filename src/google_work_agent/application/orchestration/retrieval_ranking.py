"""Deterministic RAG scoring/ranking for retrieval.rag_retrieve.

docs/05-context-retrieval.md SS5.5.

P0 scope only: exact-resource match, related-resource linkage, and keyword
lexical overlap -- computed purely from RequestIntentV2 and already-normalized
_SourceSegment metadata (context_segmentation.py). No embedding model, vector
store, reranker API, or LLM call.

The Canonical P0 signal catalog also lists participant/date/subject/status/
recency scoring. Those are intentionally NOT implemented here:
_SourceSegment (and the resource payload it is built from) carries none of
those as structured fields today -- only a flattened `text` blob assembled
from whichever of _TEXT_KEYS were present. Fabricating those signals from
ad-hoc text parsing would misrepresent them as real structural matches, so
they are a MISSING_NORMALIZED_RANKING_SIGNAL gap owned by
retrieval.normalize_segments (context_segmentation.py), not this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from google_work_agent.application.orchestration.context_segmentation import _SourceSegment
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2

EXACT_RESOURCE_REASON = "EXACT_RESOURCE"
RELATED_RESOURCE_REASON = "RELATED_RESOURCE"
KEYWORD_MATCH_REASON = "KEYWORD_MATCH"
RESOURCE_SELECTED_FORCED_REASON = "RESOURCE_SELECTED_FORCED"


class RagCandidateV1(TypedDict):
    """docs/05-context-retrieval.md SS5.5 -- Retrieval Local State only, never
    merged into Main Graph State, Domain Store, or Trace (see docs section 6/14)."""

    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]


@dataclass(frozen=True, slots=True)
class RagScoringConfig:
    """Central P0 scoring weights. Signals with no source in normalized
    Segment metadata (participant/date/subject/status/recency) have no field
    here -- adding one would imply a computation this module cannot honestly
    perform yet."""

    exact_resource_score: float = 40.0
    related_resource_score: float = 15.0
    keyword_max_score: float = 15.0
    keyword_score_per_term: float = 5.0


DEFAULT_RAG_SCORING_CONFIG = RagScoringConfig()

_MIN_QUERY_TERM_LENGTH = 2
_QUERY_TERM_CONSTRAINT_KINDS = frozenset({"PERSON", "USER_REQUIREMENT", "EMAIL"})


def rank_segments(
    segments: list[_SourceSegment],
    *,
    request_intent: RequestIntentV2,
    top_k: int,
    config: RagScoringConfig = DEFAULT_RAG_SCORING_CONFIG,
) -> list[RagCandidateV1]:
    """Score, dedup, and bound Segments to the top-K RAG candidates.

    Ordering is deterministic: retrieval_score DESC, then segment_id ASC as a
    stable tie-break (segment_id is itself an ordinal assigned during
    acquisition, so this never depends on dict/set iteration order).

    docs/05-context-retrieval.md section 7 (RESOURCE_SELECTED): a Segment
    whose resource_id is one of the user's explicitly selected resources is
    always included in the result, even if top_k would otherwise cut it --
    scoring never drops it. This never fetches a new Resource or Route; it
    only changes which already-normalized Segments survive ranking.
    """

    selected_resource_ids = _selected_resource_ids(request_intent)
    query_terms = _query_terms(request_intent)

    scored: list[tuple[_SourceSegment, float, list[str]]] = []
    seen_segment_ids: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen_segment_ids:
            continue
        seen_segment_ids.add(segment.segment_id)
        score, reason_codes = _score_segment(
            segment,
            selected_resource_ids=selected_resource_ids,
            query_terms=query_terms,
            config=config,
        )
        scored.append((segment, score, reason_codes))

    ordered = sorted(scored, key=lambda item: (-item[1], item[0].segment_id))
    top_ids = {segment.segment_id for segment, _score, _codes in ordered[:top_k]}
    forced_ids = {
        segment.segment_id
        for segment, _score, _codes in scored
        if segment.resource_id in selected_resource_ids
    } - top_ids

    candidates: list[RagCandidateV1] = []
    for segment, score, reason_codes in ordered:
        if segment.segment_id not in top_ids and segment.segment_id not in forced_ids:
            continue
        final_reason_codes = list(reason_codes)
        if segment.segment_id in forced_ids:
            final_reason_codes.append(RESOURCE_SELECTED_FORCED_REASON)
        candidates.append(
            {
                "segment_id": segment.segment_id,
                "resource_ref": segment.resource_handle,
                "retrieval_score": score,
                "reason_codes": final_reason_codes,
            }
        )
    return candidates


def _score_segment(
    segment: _SourceSegment,
    *,
    selected_resource_ids: frozenset[str],
    query_terms: frozenset[str],
    config: RagScoringConfig,
) -> tuple[float, list[str]]:
    score = 0.0
    reason_codes: list[str] = []

    if segment.resource_id in selected_resource_ids:
        score += config.exact_resource_score
        reason_codes.append(EXACT_RESOURCE_REASON)
    elif segment.parent_id is not None and segment.parent_id in selected_resource_ids:
        score += config.related_resource_score
        reason_codes.append(RELATED_RESOURCE_REASON)

    if query_terms:
        text_lower = segment.text.lower()
        matched_terms = sum(1 for term in query_terms if term in text_lower)
        if matched_terms:
            score += min(config.keyword_max_score, matched_terms * config.keyword_score_per_term)
            reason_codes.append(KEYWORD_MATCH_REASON)

    return score, reason_codes


def _selected_resource_ids(request_intent: RequestIntentV2) -> frozenset[str]:
    """RESOURCE-kind constraints carry the user's selected resource ids (see
    request-intent-v2.schema.json candidate examples: field
    "selected_resource_ids"), not a resource-type hint -- Q2-X Gate 1 already
    established that distinction for Tool Route; the same value is reused
    here for its actual documented meaning."""

    ids: set[str] = set()
    for constraint in request_intent["constraints"]:
        if constraint["kind"] != "RESOURCE":
            continue
        value = constraint["value"]
        values = value if isinstance(value, list) else [value]
        ids.update(str(item) for item in values)
    return frozenset(ids)


def _query_terms(request_intent: RequestIntentV2) -> frozenset[str]:
    terms: set[str] = set()
    terms.update(_clean_terms(request_intent["goal"]))
    for constraint in request_intent["constraints"]:
        if constraint["kind"] not in _QUERY_TERM_CONSTRAINT_KINDS:
            continue
        value = constraint["value"]
        values = value if isinstance(value, list) else [value]
        for item in values:
            terms.update(_clean_terms(str(item)))
    return frozenset(terms)


def _clean_terms(text: str) -> list[str]:
    cleaned: list[str] = []
    for token in text.split():
        stripped = token.strip(".,!?;:'\"()[]{}~`").lower()
        if len(stripped) >= _MIN_QUERY_TERM_LENGTH:
            cleaned.append(stripped)
    return cleaned
