"""Deterministic Calendar conflict policy (FN-032)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo


class CalendarConflictDecision(StrEnum):
    NO_CONFLICT = "NO_CONFLICT"
    WARNING = "WARNING"
    HARD_CONFLICT = "HARD_CONFLICT"


class CalendarConflictFreshness(StrEnum):
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    FRESH_GOOGLE_GET = "FRESH_GOOGLE_GET"


class CalendarIntervalKind(StrEnum):
    EXCLUDED = "EXCLUDED"
    WARNING = "WARNING"
    HARD = "HARD"


@dataclass(frozen=True, slots=True)
class CalendarInterval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("calendar interval must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("calendar interval start must precede end")


@dataclass(frozen=True, slots=True)
class CalendarEventCandidate:
    event_id: str
    calendar_id: str
    interval: CalendarInterval
    transparency: str | None = None
    event_type: str | None = None
    status: str | None = None
    self_response_status: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarWorkHours:
    timezone: str
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    start: str = "09:00"
    end: str = "18:00"


@dataclass(frozen=True, slots=True)
class CalendarConflictResult:
    decision: CalendarConflictDecision
    matched_resource_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def as_risk(
        self, *, checked_at_ms: int, freshness: CalendarConflictFreshness
    ) -> dict[str, object]:
        return {
            "calendar_conflict": {
                "decision": self.decision.value,
                "matched_resource_ids": list(self.matched_resource_ids),
                "reason_codes": list(self.reason_codes),
                "checked_at_ms": checked_at_ms,
                "freshness": freshness.value,
            }
        }


def intervals_overlap(left: CalendarInterval, right: CalendarInterval) -> bool:
    """Half-open overlap: adjacent intervals do not conflict."""

    return left.start < right.end and right.start < left.end


def classify_calendar_event(event: CalendarEventCandidate) -> CalendarIntervalKind:
    status = (event.status or "").casefold()
    transparency = (event.transparency or "").casefold()
    response = (event.self_response_status or "").casefold()
    event_type = (event.event_type or "").casefold()
    if status == "cancelled" or transparency in {"transparent", "free"}:
        return CalendarIntervalKind.EXCLUDED
    if response == "declined":
        return CalendarIntervalKind.EXCLUDED
    if response == "tentative" or status == "tentative":
        return CalendarIntervalKind.WARNING
    if event_type in {"outofoffice", "focustime"}:
        return CalendarIntervalKind.HARD
    return CalendarIntervalKind.HARD


def evaluate_calendar_conflict(
    *,
    proposed: CalendarInterval,
    events: tuple[CalendarEventCandidate, ...],
    freebusy: tuple[CalendarInterval, ...],
    work_hours: CalendarWorkHours,
    excluded_event_id: str | None = None,
) -> CalendarConflictResult:
    hard = False
    warning = not _inside_work_hours(proposed, work_hours)
    reasons: set[str] = {"OUTSIDE_WORK_HOURS"} if warning else set()
    matched_ids: set[str] = set()

    for event in events:
        if event.event_id == excluded_event_id or not intervals_overlap(proposed, event.interval):
            continue
        classification = classify_calendar_event(event)
        event_type = (event.event_type or "").casefold()
        if classification is CalendarIntervalKind.EXCLUDED:
            continue
        if event_type == "outofoffice":
            hard = True
            matched_ids.add(event.event_id)
            reasons.add("OUT_OF_OFFICE_OVERLAP")
        elif event_type == "focustime":
            hard = True
            matched_ids.add(event.event_id)
            reasons.add("FOCUS_TIME_OVERLAP")
        elif classification is CalendarIntervalKind.WARNING:
            warning = True
            matched_ids.add(event.event_id)
            reasons.add("TENTATIVE_EVENT_OVERLAP")
        else:
            hard = True
            matched_ids.add(event.event_id)
            reasons.add("OPAQUE_EVENT_OVERLAP")

    if any(intervals_overlap(proposed, interval) for interval in freebusy):
        hard = True
        reasons.add("BUSY_INTERVAL_OVERLAP")

    decision = (
        CalendarConflictDecision.HARD_CONFLICT
        if hard
        else CalendarConflictDecision.WARNING
        if warning
        else CalendarConflictDecision.NO_CONFLICT
    )
    if not reasons:
        reasons.add("NO_CONFLICT")
    return CalendarConflictResult(
        decision=decision,
        matched_resource_ids=tuple(sorted(matched_ids)),
        reason_codes=tuple(sorted(reasons)),
    )


def _inside_work_hours(interval: CalendarInterval, work_hours: CalendarWorkHours) -> bool:
    timezone = ZoneInfo(work_hours.timezone)
    start = interval.start.astimezone(timezone)
    end = interval.end.astimezone(timezone)
    if start.date() != end.date() or start.weekday() not in work_hours.days:
        return False
    opening = time.fromisoformat(work_hours.start)
    closing = time.fromisoformat(work_hours.end)
    return (
        start.timetz().replace(tzinfo=None) >= opening
        and end.timetz().replace(tzinfo=None) <= closing
    )


__all__ = [
    "CalendarConflictDecision",
    "CalendarConflictFreshness",
    "CalendarConflictResult",
    "CalendarEventCandidate",
    "CalendarInterval",
    "CalendarIntervalKind",
    "CalendarWorkHours",
    "evaluate_calendar_conflict",
    "classify_calendar_event",
    "intervals_overlap",
]
