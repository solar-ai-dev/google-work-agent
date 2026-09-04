"""Prioritize content-bearing Gmail candidates before bounded detail retrieval."""

from __future__ import annotations

import re
from collections.abc import Collection

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1

_CONTENT_RECORD_MARKERS = (
    "회의록",
    "회의 기록",
    "회의 메모",
    "meeting minutes",
    "minutes",
    "agenda",
    "안건",
    "결정 사항",
    "action item",
)
_WORK_TRACKING_MARKERS = ("jira", "asana", "linear", "trello", "project")
_SYSTEM_NOTIFICATION_MARKERS = (
    "새 공지",
    "알림 설정",
    "notification",
    "newsletter",
    "welcome",
    "새로운 수신함",
    "new feature",
)
_LINEAGE_PATTERN = re.compile(r"(?<![A-Z0-9])[A-Z][A-Z0-9]+-\d+(?![A-Z0-9])", re.IGNORECASE)


def prioritize_material_gmail_evidence(
    selection: EvidenceSelectionResultV2,
    *,
    request_intent: RequestIntentV2,
    rag_candidates: list[RagCandidateV1],
    segments: list[SourceSegment],
    max_evidence: int,
) -> EvidenceSelectionResultV2:
    """Promote meeting records over notification metadata for vague analysis reads."""

    if not _requires_vague_gmail_analysis(request_intent):
        return selection
    by_id = {segment.segment_id: segment for segment in segments}
    ranked = sorted(
        (
            (_materiality_score(by_id[candidate["segment_id"]].text), index, candidate)
            for index, candidate in enumerate(rag_candidates)
            if candidate["segment_id"] in by_id
            and candidate["resource_ref"].startswith("gmail_thread:")
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not ranked or ranked[0][0] <= 0:
        return selection

    primary = ranked[0][2]
    primary_segment = by_id[primary["segment_id"]]
    lineage_keys = _lineage_keys(primary_segment.text)
    promoted_ids = [primary["segment_id"]]
    if lineage_keys:
        promoted_ids.extend(
            candidate["segment_id"]
            for score, _, candidate in ranked[1:]
            if score > 0
            and lineage_keys.intersection(_lineage_keys(by_id[candidate["segment_id"]].text))
        )
    promoted_ids = _stable_unique(promoted_ids)[:max_evidence]

    selected = _stable_unique([*promoted_ids, *selection["selected_segment_ids"]])[:max_evidence]
    selected_set = set(selected)
    existing_drafts = {draft["segment_id"]: draft for draft in selection["evidence_drafts"]}
    evidence_drafts = [
        existing_drafts.get(
            segment_id,
            {
                "segment_id": segment_id,
                "role": "SUPPORTS",
                "relevance_reason": "CONTENT_BEARING_WORK_RECORD",
            },
        )
        for segment_id in selected
    ]
    return {
        "schema_version": 2,
        "evidence_drafts": evidence_drafts,
        "selected_segment_ids": selected,
        "excluded_segment_ids": [
            segment_id
            for segment_id in selection["excluded_segment_ids"]
            if segment_id not in selected_set
        ],
    }


def _requires_vague_gmail_analysis(request_intent: RequestIntentV2) -> bool:
    return (
        request_intent["analysis_requirement"] == "REQUIRED"
        and request_intent["requested_effect_hints"] == ["READ"]
        and "GMAIL_THREAD" in request_intent["requested_resource_hints"]
        and any(
            constraint["kind"] == "USER_REQUIREMENT"
            and constraint["field"] == "original_search_request"
            for constraint in request_intent["constraints"]
        )
    )


def _materiality_score(text: str) -> int:
    normalized = text.casefold()
    score = 0
    if any(marker in normalized for marker in _CONTENT_RECORD_MARKERS):
        score += 5
    if any(marker in normalized for marker in _WORK_TRACKING_MARKERS):
        score += 2
    if any(marker in normalized for marker in _SYSTEM_NOTIFICATION_MARKERS):
        score -= 5
    return score


def _lineage_keys(text: str) -> frozenset[str]:
    return frozenset(match.group(0).upper() for match in _LINEAGE_PATTERN.finditer(text))


def _stable_unique(values: Collection[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = ["prioritize_material_gmail_evidence"]
