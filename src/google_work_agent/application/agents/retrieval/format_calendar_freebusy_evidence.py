"""Keep availability-query scope distinct from an actual Calendar event."""

import json


def format_calendar_freebusy_evidence(payload: dict[str, object]) -> str:
    start = payload.get("time_min")
    end = payload.get("time_max")
    busy = payload.get("busy_intervals")
    if not isinstance(start, str) or not isinstance(end, str) or not isinstance(busy, list):
        raise ValueError("FreeBusy evidence requires query bounds and explicit busy intervals")
    return (
        "Calendar FreeBusy availability query; not an event or a write result.\n"
        f"query_time_min: {start}\nquery_time_max: {end}\n"
        f"busy_intervals: {json.dumps(busy, ensure_ascii=False, sort_keys=True)}"
    )
