"""Deterministic duplicate validation for Google Task creation (FN-031)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class DuplicateDecision(StrEnum):
    NOT_DUPLICATE = "NOT_DUPLICATE"
    SIMILAR_CANDIDATE = "SIMILAR_CANDIDATE"
    CLEAR_DUPLICATE = "CLEAR_DUPLICATE"


class DuplicateFreshness(StrEnum):
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    FRESH_GOOGLE_GET = "FRESH_GOOGLE_GET"


@dataclass(frozen=True, slots=True)
class TaskDuplicateCandidate:
    resource_id: str
    title: str
    scheduled_date: str | None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class TaskDuplicateResult:
    decision: DuplicateDecision
    matched_resource_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def as_risk(self, *, checked_at_ms: int, freshness: DuplicateFreshness) -> dict[str, object]:
        return {
            "duplicate": {
                "decision": self.decision.value,
                "matched_resource_ids": list(self.matched_resource_ids),
                "reason_codes": list(self.reason_codes),
                "checked_at_ms": checked_at_ms,
                "freshness": freshness.value,
            }
        }


_WHITESPACE = re.compile(r"\s+")


def normalize_task_title(title: str) -> str:
    """Apply only the canonical FN-031 title normalization operations."""

    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", title).strip()).casefold()


def normalize_scheduled_date(value: object) -> str | None:
    """Map a Google Task ``due`` value to its date-only scheduled_date."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("task due must be a string or null")
    normalized = value.strip()
    if not normalized:
        return None
    candidate = normalized[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as error:
        raise ValueError("task due must begin with an ISO calendar date") from error


def evaluate_task_duplicate(
    *,
    title: str,
    scheduled_date: str | None,
    candidates: tuple[TaskDuplicateCandidate, ...],
) -> TaskDuplicateResult:
    """Classify exact-title incomplete Tasks without fuzzy heuristics."""

    normalized_title = normalize_task_title(title)
    exact_date_ids: set[str] = set()
    different_date_ids: set[str] = set()
    for candidate in candidates:
        if _is_completed(candidate.status):
            continue
        if normalize_task_title(candidate.title) != normalized_title:
            continue
        if candidate.scheduled_date == scheduled_date:
            exact_date_ids.add(candidate.resource_id)
        else:
            different_date_ids.add(candidate.resource_id)

    if exact_date_ids:
        return TaskDuplicateResult(
            decision=DuplicateDecision.CLEAR_DUPLICATE,
            matched_resource_ids=tuple(sorted(exact_date_ids)),
            reason_codes=("TITLE_EXACT_DATE_EXACT",),
        )
    if different_date_ids:
        return TaskDuplicateResult(
            decision=DuplicateDecision.SIMILAR_CANDIDATE,
            matched_resource_ids=tuple(sorted(different_date_ids)),
            reason_codes=("TITLE_EXACT_DATE_DIFFERENT",),
        )
    return TaskDuplicateResult(
        decision=DuplicateDecision.NOT_DUPLICATE,
        matched_resource_ids=(),
        reason_codes=("NO_MATCHING_INCOMPLETE_TASK",),
    )


def _is_completed(status: str | None) -> bool:
    return status is not None and status.casefold() == "completed"


__all__ = [
    "DuplicateDecision",
    "DuplicateFreshness",
    "TaskDuplicateCandidate",
    "TaskDuplicateResult",
    "evaluate_task_duplicate",
    "normalize_scheduled_date",
    "normalize_task_title",
]
