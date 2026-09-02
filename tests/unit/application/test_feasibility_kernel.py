from __future__ import annotations

from datetime import datetime

import pytest

from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarInterval,
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.feasibility_policy import (
    FeasibilityDecision,
    derive_deadline_cutoff,
    evaluate_feasibility,
    merge_intervals,
)

WORK_HOURS = CalendarWorkHours(timezone="Asia/Seoul")
NOW = datetime.fromisoformat("2026-08-12T09:00:00+09:00")


def interval(start: str, end: str) -> CalendarInterval:
    return CalendarInterval(datetime.fromisoformat(start), datetime.fromisoformat(end))


@pytest.mark.parametrize(
    ("duration", "hard", "warning", "decision"),
    [
        (120, (), (), FeasibilityDecision.FEASIBLE),
        (
            120,
            (interval("2026-08-12T11:30:00+09:00", "2026-08-12T18:00:00+09:00"),),
            (interval("2026-08-12T10:00:00+09:00", "2026-08-12T11:30:00+09:00"),),
            FeasibilityDecision.RISK,
        ),
        (
            120,
            (interval("2026-08-12T10:30:00+09:00", "2026-08-12T18:00:00+09:00"),),
            (),
            FeasibilityDecision.INFEASIBLE,
        ),
        (540, (), (), FeasibilityDecision.FEASIBLE),
    ],
)
def test_deterministic_decisions__for_feasibility_kernel__matches_expected_contract(
    duration: int,
    hard: tuple[CalendarInterval, ...],
    warning: tuple[CalendarInterval, ...],
    decision: FeasibilityDecision,
) -> None:
    result = evaluate_feasibility(
        now=NOW,
        business_deadline="2026-08-12",
        required_duration_minutes=duration,
        work_hours=WORK_HOURS,
        hard_busy=hard,
        warning_busy=warning,
    )
    assert result.decision is decision


def test_fragmented_slots__are_not__summed() -> None:
    result = evaluate_feasibility(
        now=NOW,
        business_deadline="2026-08-12T12:00:00+09:00",
        required_duration_minutes=120,
        work_hours=WORK_HOURS,
        hard_busy=(interval("2026-08-12T10:00:00+09:00", "2026-08-12T11:00:00+09:00"),),
        warning_busy=(),
    )
    assert result.decision is FeasibilityDecision.INFEASIBLE
    assert result.best_warning_slot_minutes == 60


def test_passed_deadline__is__infeasible() -> None:
    result = evaluate_feasibility(
        now=NOW,
        business_deadline="2026-08-12T08:59:00+09:00",
        required_duration_minutes=1,
        work_hours=WORK_HOURS,
        hard_busy=(),
        warning_busy=(),
    )
    assert result.decision is FeasibilityDecision.INFEASIBLE
    assert result.reason_codes == ("DEADLINE_PASSED",)


def test_date_only_cutoff_uses__work_hours_end_and__weekend_adds_no_slot() -> None:
    cutoff = derive_deadline_cutoff("2026-08-15", work_hours=WORK_HOURS)
    assert cutoff.isoformat() == "2026-08-15T18:00:00+09:00"
    result = evaluate_feasibility(
        now=datetime.fromisoformat("2026-08-15T09:00:00+09:00"),
        business_deadline="2026-08-15",
        required_duration_minutes=1,
        work_hours=WORK_HOURS,
        hard_busy=(),
        warning_busy=(),
    )
    assert result.decision is FeasibilityDecision.INFEASIBLE


def test_exact_datetime__is_cutoff_and__naive_is_rejected() -> None:
    cutoff = derive_deadline_cutoff("2026-08-12T13:30:00+09:00", work_hours=WORK_HOURS)
    assert cutoff.hour == 13 and cutoff.minute == 30
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_deadline_cutoff("2026-08-12T13:30:00", work_hours=WORK_HOURS)


def test_overlapping_adjacent__and_duplicate__busy_merge_deterministically() -> None:
    merged = merge_intervals(
        (
            interval("2026-08-12T10:30:00+09:00", "2026-08-12T12:00:00+09:00"),
            interval("2026-08-12T10:00:00+09:00", "2026-08-12T11:00:00+09:00"),
            interval("2026-08-12T12:00:00+09:00", "2026-08-12T13:00:00+09:00"),
            interval("2026-08-12T10:00:00+09:00", "2026-08-12T11:00:00+09:00"),
        )
    )
    assert merged == (interval("2026-08-12T10:00:00+09:00", "2026-08-12T13:00:00+09:00"),)


def test_duration_must__be__positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        evaluate_feasibility(
            now=NOW,
            business_deadline="2026-08-12",
            required_duration_minutes=0,
            work_hours=WORK_HOURS,
            hard_busy=(),
            warning_busy=(),
        )


def test_dst_transition_uses__elapsed_minutes_not__wall_clock_labels() -> None:
    result = evaluate_feasibility(
        now=datetime.fromisoformat("2026-03-08T01:00:00-05:00"),
        business_deadline="2026-03-08T04:00:00-04:00",
        required_duration_minutes=150,
        work_hours=CalendarWorkHours(
            timezone="America/New_York", days=(6,), start="01:00", end="04:00"
        ),
        hard_busy=(),
        warning_busy=(),
    )
    assert result.decision is FeasibilityDecision.INFEASIBLE
    assert result.best_warning_slot_minutes == 120
