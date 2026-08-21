"""Canonical Retrieval deterministic operation: rag_retrieve_rerank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from google_work_agent.application.workflows.handoff_contracts import RequestIntentV2
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment


class RagCandidateV1(TypedDict):
    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]


@dataclass(frozen=True, slots=True)
class RagScoringConfig:
    exact_resource_score: float = 40.0
    related_resource_score: float = 15.0
    keyword_max_score: float = 15.0
    keyword_score_per_term: float = 5.0


DEFAULT_RAG_SCORING_CONFIG = RagScoringConfig()
_MIN_QUERY_TERM_LENGTH = 2
_QUERY_TERM_CONSTRAINT_KINDS = frozenset({"PERSON", "USER_REQUIREMENT", "EMAIL"})


def rag_retrieve_rerank(
    segments: list[SourceSegment],
    *,
    request_intent: RequestIntentV2,
    top_k: int,
    config: RagScoringConfig = DEFAULT_RAG_SCORING_CONFIG,
) -> list[RagCandidateV1]:
    """Deterministically score, deduplicate, rank, and bound normalized segments."""
    selected = _selected_resource_ids(request_intent)
    terms = _query_terms(request_intent)
    scored: list[tuple[SourceSegment, float, list[str]]] = []
    seen: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen:
            continue
        seen.add(segment.segment_id)
        score = 0.0
        reasons: list[str] = []
        if segment.resource_id in selected:
            score += config.exact_resource_score
            reasons.append("EXACT_RESOURCE")
        elif segment.parent_id is not None and segment.parent_id in selected:
            score += config.related_resource_score
            reasons.append("RELATED_RESOURCE")
        matched = sum(1 for term in terms if term in segment.text.lower())
        if matched:
            score += min(config.keyword_max_score, matched * config.keyword_score_per_term)
            reasons.append("KEYWORD_MATCH")
        scored.append((segment, score, reasons))

    ordered = sorted(scored, key=lambda item: (-item[1], item[0].segment_id))
    top_ids = {segment.segment_id for segment, _, _ in ordered[:top_k]}
    forced = {
        segment.segment_id
        for segment, _, _ in scored
        if segment.resource_id in selected and segment.segment_id not in top_ids
    }
    return [
        {
            "segment_id": segment.segment_id,
            "resource_ref": segment.resource_handle,
            "retrieval_score": score,
            "reason_codes": reasons + (["RESOURCE_SELECTED_FORCED"] if segment.segment_id in forced else []),
        }
        for segment, score, reasons in ordered
        if segment.segment_id in top_ids or segment.segment_id in forced
    ]


def _selected_resource_ids(intent: RequestIntentV2) -> frozenset[str]:
    ids: set[str] = set()
    for constraint in intent["constraints"]:
        if constraint["kind"] == "RESOURCE":
            value = constraint["value"]
            ids.update(str(item) for item in (value if isinstance(value, list) else [value]))
    return frozenset(ids)


def _query_terms(intent: RequestIntentV2) -> frozenset[str]:
    terms = set(_clean_terms(intent["goal"]))
    for constraint in intent["constraints"]:
        if constraint["kind"] in _QUERY_TERM_CONSTRAINT_KINDS:
            value = constraint["value"]
            for item in value if isinstance(value, list) else [value]:
                terms.update(_clean_terms(str(item)))
    return frozenset(terms)


def _clean_terms(text: str) -> list[str]:
    return [
        cleaned
        for token in text.split()
        if len(cleaned := token.strip(".,!?;:'\"()[]{}~`").lower()) >= _MIN_QUERY_TERM_LENGTH
    ]
