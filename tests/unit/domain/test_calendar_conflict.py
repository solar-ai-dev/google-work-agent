from __future__ import annotations

from datetime import datetime

import pytest

from google_work_agent.domain.calendar_conflict import (
    CalendarConflictDecision,
    CalendarEventCandidate,
    CalendarInterval,
    CalendarWorkHours,
    evaluate_calendar_conflict,
    intervals_overlap,
)


def interval(start: str, end: str) -> CalendarInterval:
    return CalendarInterval(datetime.fromisoformat(start), datetime.fromisoformat(end))


@pytest.mark.parametrize(
    ("other_start", "other_end", "expected"),
    [
        ("2026-08-12T09:00:00+09:00", "2026-08-12T10:30:00+09:00", True),
        ("2026-08-12T09:30:00+09:00", "2026-08-12T11:00:00+09:00", True),
        ("2026-08-12T09:15:00+09:00", "2026-08-12T09:45:00+09:00", True),
        ("2026-08-12T10:00:00+09:00", "2026-08-12T11:00:00+09:00", False),
    ],
)
def test_half_open_overlap(other_start: str, other_end: str, expected: bool) -> None:
    proposed = interval("2026-08-12T09:00:00+09:00", "2026-08-12T10:00:00+09:00")
    assert intervals_overlap(proposed, interval(other_start, other_end)) is expected


@pytest.mark.parametrize(
    ("fields", "decision", "reason"),
    [
        ({}, CalendarConflictDecision.HARD_CONFLICT, "OPAQUE_EVENT_OVERLAP"),
        (
            {"transparency": "opaque"},
            CalendarConflictDecision.HARD_CONFLICT,
            "OPAQUE_EVENT_OVERLAP",
        ),
        (
            {"event_type": "outOfOffice"},
            CalendarConflictDecision.HARD_CONFLICT,
            "OUT_OF_OFFICE_OVERLAP",
        ),
        ({"event_type": "focusTime"}, CalendarConflictDecision.HARD_CONFLICT, "FOCUS_TIME_OVERLAP"),
        (
            {"self_response_status": "tentative"},
            CalendarConflictDecision.WARNING,
            "TENTATIVE_EVENT_OVERLAP",
        ),
        ({"status": "tentative"}, CalendarConflictDecision.WARNING, "TENTATIVE_EVENT_OVERLAP"),
        ({"transparency": "transparent"}, CalendarConflictDecision.NO_CONFLICT, "NO_CONFLICT"),
        ({"transparency": "free"}, CalendarConflictDecision.NO_CONFLICT, "NO_CONFLICT"),
        ({"self_response_status": "declined"}, CalendarConflictDecision.NO_CONFLICT, "NO_CONFLICT"),
        ({"status": "cancelled"}, CalendarConflictDecision.NO_CONFLICT, "NO_CONFLICT"),
    ],
)
def test_event_classification(
    fields: dict[str, str], decision: CalendarConflictDecision, reason: str
) -> None:
    proposed = interval("2026-08-12T09:00:00+09:00", "2026-08-12T10:00:00+09:00")
    event = CalendarEventCandidate(
        event_id="event-1", calendar_id="primary", interval=proposed, **fields
    )
    result = evaluate_calendar_conflict(
        proposed=proposed,
        events=(event,),
        freebusy=(),
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
    )
    assert result.decision is decision
    assert reason in result.reason_codes


def test_freebusy_is_hard_and_does_not_invent_resource_id() -> None:
    proposed = interval("2026-08-12T09:00:00+09:00", "2026-08-12T10:00:00+09:00")
    result = evaluate_calendar_conflict(
        proposed=proposed,
        events=(),
        freebusy=(proposed,),
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
    )
    assert result.decision is CalendarConflictDecision.HARD_CONFLICT
    assert result.matched_resource_ids == ()
    assert result.reason_codes == ("BUSY_INTERVAL_OVERLAP",)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-08-12T08:59:00+09:00", "2026-08-12T10:00:00+09:00"),
        ("2026-08-12T17:00:00+09:00", "2026-08-12T18:01:00+09:00"),
        ("2026-08-15T10:00:00+09:00", "2026-08-15T11:00:00+09:00"),
    ],
)
def test_outside_work_hours_is_warning(start: str, end: str) -> None:
    result = evaluate_calendar_conflict(
        proposed=interval(start, end),
        events=(),
        freebusy=(),
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
    )
    assert result.decision is CalendarConflictDecision.WARNING
    assert result.reason_codes == ("OUTSIDE_WORK_HOURS",)


def test_update_excludes_only_target_event() -> None:
    proposed = interval("2026-08-12T09:00:00+09:00", "2026-08-12T10:00:00+09:00")
    events = tuple(
        CalendarEventCandidate(event_id=value, calendar_id="primary", interval=proposed)
        for value in ("target", "other")
    )
    result = evaluate_calendar_conflict(
        proposed=proposed,
        events=events,
        freebusy=(),
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
        excluded_event_id="target",
    )
    assert result.matched_resource_ids == ("other",)


def test_invalid_or_naive_interval_is_rejected() -> None:
    with pytest.raises(ValueError):
        CalendarInterval(datetime(2026, 8, 12, 9), datetime(2026, 8, 12, 10))
    with pytest.raises(ValueError):
        interval("2026-08-12T10:00:00+09:00", "2026-08-12T10:00:00+09:00")
