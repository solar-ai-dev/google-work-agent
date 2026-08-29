"""Provider-neutral deterministic availability interval arithmetic."""

from __future__ import annotations

from datetime import datetime
from typing import Required, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BusyIntervalV1(TypedDict):
    start: Required[str]
    end: Required[str]
    resource_ref: Required[str]


class AvailableIntervalV1(TypedDict):
    start: Required[str]
    end: Required[str]
    timezone: Required[str]
    derived_from_resource_refs: Required[list[str]]


def resolve_availability(
    *,
    window_start: str,
    window_end: str,
    timezone: str,
    busy_intervals: list[BusyIntervalV1],
    minimum_duration_seconds: int = 0,
) -> list[AvailableIntervalV1]:
    """Intersect busy intervals with the window and return their deterministic complement."""
    if minimum_duration_seconds < 0:
        raise ValueError("minimum_duration_seconds cannot be negative")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone must be a valid IANA timezone") from error
    start = _instant(window_start, zone)
    end = _instant(window_end, zone)
    if start >= end:
        raise ValueError("availability window must be increasing")

    normalized: list[tuple[datetime, datetime, set[str]]] = []
    for interval in busy_intervals:
        busy_start = max(start, _instant(interval["start"], zone))
        busy_end = min(end, _instant(interval["end"], zone))
        if busy_start >= busy_end:
            continue
        refs = {interval["resource_ref"]} if interval["resource_ref"] else set()
        if normalized and busy_start <= normalized[-1][1]:
            previous_start, previous_end, previous_refs = normalized[-1]
            normalized[-1] = (
                previous_start,
                max(previous_end, busy_end),
                previous_refs | refs,
            )
        else:
            normalized.append((busy_start, busy_end, refs))

    result: list[AvailableIntervalV1] = []
    cursor = start
    all_refs = sorted({ref for _, _, refs in normalized for ref in refs})
    for busy_start, busy_end, _ in normalized:
        _append_available(result, cursor, busy_start, timezone, all_refs, minimum_duration_seconds)
        cursor = max(cursor, busy_end)
    _append_available(result, cursor, end, timezone, all_refs, minimum_duration_seconds)
    return result


def _instant(value: str, zone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("interval boundary must be ISO-8601") from error
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def _append_available(
    result: list[AvailableIntervalV1],
    start: datetime,
    end: datetime,
    timezone: str,
    refs: list[str],
    minimum_duration_seconds: int,
) -> None:
    if start >= end or (end - start).total_seconds() < minimum_duration_seconds:
        return
    result.append(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
            "derived_from_resource_refs": refs,
        }
    )


__all__ = ["AvailableIntervalV1", "BusyIntervalV1", "resolve_availability"]
