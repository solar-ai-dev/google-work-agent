"""Deterministic contiguous-slot feasibility policy (FN-033)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from google_work_agent.application.policy_kernels.calendar_conflict import (
    CalendarInterval,
    CalendarWorkHours,
)


class FeasibilityDecision(StrEnum):
    FEASIBLE = "FEASIBLE"
    RISK = "RISK"
    INFEASIBLE = "INFEASIBLE"


class FeasibilityFreshness(StrEnum):
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    FRESH_GOOGLE_GET = "FRESH_GOOGLE_GET"


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    decision: FeasibilityDecision
    reason_codes: tuple[str, ...]
    business_deadline: str
    derived_cutoff: datetime
    required_duration_minutes: int
    best_clean_slot_minutes: int
    best_warning_slot_minutes: int

    def as_risk(self, *, checked_at_ms: int, freshness: FeasibilityFreshness) -> dict[str, object]:
        return {
            "feasibility": {
                "decision": self.decision.value,
                "reason_codes": list(self.reason_codes),
                "business_deadline": self.business_deadline,
                "derived_cutoff": self.derived_cutoff.isoformat(),
                "required_duration_minutes": self.required_duration_minutes,
                "best_clean_slot_minutes": self.best_clean_slot_minutes,
                "best_warning_slot_minutes": self.best_warning_slot_minutes,
                "checked_at_ms": checked_at_ms,
                "freshness": freshness.value,
            }
        }


def evaluate_feasibility(
    *,
    now: datetime,
    business_deadline: str,
    required_duration_minutes: int,
    work_hours: CalendarWorkHours,
    hard_busy: tuple[CalendarInterval, ...],
    warning_busy: tuple[CalendarInterval, ...],
) -> FeasibilityResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("feasibility now must be timezone-aware")
    if required_duration_minutes <= 0:
        raise ValueError("required duration must be positive")
    cutoff = derive_deadline_cutoff(business_deadline, work_hours=work_hours)
    if cutoff <= now:
        return FeasibilityResult(
            decision=FeasibilityDecision.INFEASIBLE,
            reason_codes=("DEADLINE_PASSED",),
            business_deadline=business_deadline,
            derived_cutoff=cutoff,
            required_duration_minutes=required_duration_minutes,
            best_clean_slot_minutes=0,
            best_warning_slot_minutes=0,
        )

    work_intervals = build_work_intervals(now=now, cutoff=cutoff, work_hours=work_hours)
    hard = merge_intervals(hard_busy)
    warning = merge_intervals(warning_busy)
    warning_capable = subtract_intervals(work_intervals, hard)
    clean = subtract_intervals(warning_capable, warning)
    best_clean = _best_minutes(clean)
    best_warning = _best_minutes(warning_capable)
    if best_clean >= required_duration_minutes:
        decision = FeasibilityDecision.FEASIBLE
        reasons = ("CLEAN_SLOT_AVAILABLE",)
    elif best_warning >= required_duration_minutes:
        decision = FeasibilityDecision.RISK
        reasons = ("TENTATIVE_SLOT_ONLY",)
    else:
        decision = FeasibilityDecision.INFEASIBLE
        reasons = ("NO_CONTIGUOUS_SLOT",)
    return FeasibilityResult(
        decision=decision,
        reason_codes=reasons,
        business_deadline=business_deadline,
        derived_cutoff=cutoff,
        required_duration_minutes=required_duration_minutes,
        best_clean_slot_minutes=best_clean,
        best_warning_slot_minutes=best_warning,
    )


def derive_deadline_cutoff(business_deadline: str, *, work_hours: CalendarWorkHours) -> datetime:
    timezone = ZoneInfo(work_hours.timezone)
    value = business_deadline.strip()
    if len(value) == 10:
        deadline_date = date.fromisoformat(value)
        return datetime.combine(deadline_date, time.fromisoformat(work_hours.end), timezone)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("business deadline datetime must be timezone-aware")
    return parsed


def build_work_intervals(
    *, now: datetime, cutoff: datetime, work_hours: CalendarWorkHours
) -> tuple[CalendarInterval, ...]:
    timezone = ZoneInfo(work_hours.timezone)
    local_now = now.astimezone(timezone)
    local_cutoff = cutoff.astimezone(timezone)
    current = local_now.date()
    result: list[CalendarInterval] = []
    while current <= local_cutoff.date():
        if current.weekday() in work_hours.days:
            start = datetime.combine(current, time.fromisoformat(work_hours.start), timezone)
            end = datetime.combine(current, time.fromisoformat(work_hours.end), timezone)
            bounded_start = max(start, local_now)
            bounded_end = min(end, local_cutoff)
            if bounded_start < bounded_end:
                result.append(CalendarInterval(bounded_start, bounded_end))
        current += timedelta(days=1)
    return tuple(result)


def merge_intervals(intervals: tuple[CalendarInterval, ...]) -> tuple[CalendarInterval, ...]:
    if not intervals:
        return ()
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    merged: list[CalendarInterval] = [ordered[0]]
    for interval in ordered[1:]:
        previous = merged[-1]
        if interval.start <= previous.end:
            merged[-1] = CalendarInterval(previous.start, max(previous.end, interval.end))
        else:
            merged.append(interval)
    return tuple(merged)


def subtract_intervals(
    sources: tuple[CalendarInterval, ...],
    exclusions: tuple[CalendarInterval, ...],
) -> tuple[CalendarInterval, ...]:
    result: list[CalendarInterval] = []
    for source in sources:
        fragments = [source]
        for exclusion in exclusions:
            next_fragments: list[CalendarInterval] = []
            for fragment in fragments:
                if exclusion.end <= fragment.start or exclusion.start >= fragment.end:
                    next_fragments.append(fragment)
                    continue
                if fragment.start < exclusion.start:
                    next_fragments.append(
                        CalendarInterval(fragment.start, min(fragment.end, exclusion.start))
                    )
                if exclusion.end < fragment.end:
                    next_fragments.append(
                        CalendarInterval(max(fragment.start, exclusion.end), fragment.end)
                    )
            fragments = next_fragments
        result.extend(fragments)
    return tuple(result)


def _best_minutes(intervals: tuple[CalendarInterval, ...]) -> int:
    return max(
        (
            int((item.end.astimezone(UTC) - item.start.astimezone(UTC)).total_seconds() // 60)
            for item in intervals
        ),
        default=0,
    )


__all__ = [
    "FeasibilityDecision",
    "FeasibilityFreshness",
    "FeasibilityResult",
    "build_work_intervals",
    "derive_deadline_cutoff",
    "evaluate_feasibility",
    "merge_intervals",
    "subtract_intervals",
]
