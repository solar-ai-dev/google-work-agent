"""Resolve user relative periods into provider-neutral retrieval bounds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ResolvedTemporalRange(TypedDict):
    kind: Literal["TEMPORAL_RANGE"]
    axis: Literal["MESSAGE_TIME"]
    start_local: str
    end_local: str
    timezone: str


def resolve_relative_period(
    constraints: object,
    *,
    now_ms: int,
    timezone: str,
) -> ResolvedTemporalRange | None:
    """Resolve one supported relative period from current user-local time."""

    periods = _relative_periods(constraints)
    if len(periods) != 1:
        return None
    try:
        local_now = datetime.fromtimestamp(now_ms / 1_000, tz=ZoneInfo(timezone))
    except (OSError, OverflowError, ValueError, ZoneInfoNotFoundError):
        return None

    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    period = periods[0]
    if period == "오늘":
        start, end = today, today + timedelta(days=1)
    elif period == "어제":
        start, end = today - timedelta(days=1), today
    elif period == "그제":
        start, end = today - timedelta(days=2), today - timedelta(days=1)
    elif period in {"지난주", "이번주", "다음주"}:
        this_week = today - timedelta(days=today.weekday())
        offset = {"지난주": -7, "이번주": 0, "다음주": 7}[period]
        start = this_week + timedelta(days=offset)
        end = start + timedelta(days=7)
    elif period in {"지난달", "이번달"}:
        this_month = today.replace(day=1)
        if period == "지난달":
            end = this_month
            start = (this_month - timedelta(days=1)).replace(day=1)
        else:
            start = this_month
            end = (this_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif period == "최근":
        start, end = today - timedelta(days=30), today + timedelta(days=1)
    else:
        return None

    return {
        "kind": "TEMPORAL_RANGE",
        "axis": "MESSAGE_TIME",
        "start_local": start.replace(tzinfo=None).isoformat(),
        "end_local": end.replace(tzinfo=None).isoformat(),
        "timezone": timezone,
    }


def _relative_periods(constraints: object) -> list[str]:
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return []
    result: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping):
            continue
        if item.get("kind") != "DATE" or item.get("field") != "period":
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        result.extend(
            str(value).replace(" ", "")
            for value in values
            if isinstance(value, str) and value.strip()
        )
    return list(dict.fromkeys(result))


__all__ = ["ResolvedTemporalRange", "resolve_relative_period"]
