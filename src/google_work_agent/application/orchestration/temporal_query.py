"""Deterministic normalization of typed acquisition temporal queries."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.orchestration.handoff_contracts import TemporalQueryV1
from google_work_agent.ports.connector.contracts.google_workspace import TimeRange

_DAYPART_WINDOWS: dict[str, tuple[time, time]] = {
    "MORNING": (time(6, 0), time(12, 0)),
    "AFTERNOON": (time(12, 0), time(18, 0)),
    "EVENING": (time(18, 0), time(21, 0)),
}
_WEEKDAY_INDEX = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


def resolve_temporal_query(
    *, temporal_query: TemporalQueryV1, now_ms: int, timezone: str
) -> TimeRange | None:
    """Resolve a validated typed query without reinterpreting request text."""
    if temporal_query["relation"] == "ABSOLUTE":
        start = temporal_query["absolute_start"]
        end = temporal_query["absolute_end"]
        if start is None or end is None:
            return None
        try:
            return TimeRange(start=start, end=end)
        except ValueError:
            return None
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    now_local = datetime.fromtimestamp(now_ms / 1000, tz=UTC).astimezone(tz)
    unit = temporal_query["relative_unit"]
    offset = temporal_query["relative_offset"]
    if unit is None or offset is None:
        return None
    if unit == "DAY":
        window_start_date = (now_local + timedelta(days=offset)).date()
        window_end_date = window_start_date + timedelta(days=1)
    elif unit == "WEEK":
        monday = now_local.date() - timedelta(days=now_local.weekday())
        window_start_date = monday + timedelta(weeks=offset)
        window_end_date = window_start_date + timedelta(days=7)
    else:
        return None
    weekday = temporal_query["weekday"]
    if weekday is not None and unit == "WEEK":
        target_index = _WEEKDAY_INDEX[weekday]
        day_offset = (target_index - window_start_date.weekday()) % 7
        candidate = window_start_date + timedelta(days=day_offset)
        if candidate >= window_end_date:
            return None
        window_start_date = candidate
        window_end_date = candidate + timedelta(days=1)
    daypart = temporal_query["daypart"]
    if daypart is not None:
        start_time, end_time = _DAYPART_WINDOWS[daypart]
        start_dt = datetime.combine(window_start_date, start_time, tzinfo=tz)
        end_dt = datetime.combine(window_start_date, end_time, tzinfo=tz)
    else:
        start_dt = datetime.combine(window_start_date, time.min, tzinfo=tz)
        end_dt = datetime.combine(window_end_date, time.min, tzinfo=tz)
    try:
        return TimeRange(start=start_dt.isoformat(), end=end_dt.isoformat())
    except ValueError:
        return None
