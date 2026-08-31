"""Action-owner-local deterministic Calendar conflict checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarConflictDecision,
    CalendarConflictFreshness,
    CalendarEventCandidate,
    CalendarInterval,
    CalendarWorkHours,
    evaluate_calendar_conflict,
)
from google_work_agent.domain.action.model import PolicyViolationError, normalize_action_risk
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)

CALENDAR_CREATE_TOOL = "calendar_create_event"
CALENDAR_UPDATE_TOOL = "calendar_update_event"
CALENDAR_CONFLICT_TOOLS = frozenset({CALENDAR_CREATE_TOOL, CALENDAR_UPDATE_TOOL})
CALENDAR_CONFLICT_PAGE_SIZE = 250
CALENDAR_CONFLICT_BUFFER_SECONDS = 0


class CalendarConflictGateway(Protocol):
    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot: ...

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str | None = None,
        time_max: str | None = None,
        single_events: bool = False,
        order_by: str | None = None,
    ) -> ResourcePage: ...

    def query_freebusy(
        self, *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]: ...


class CalendarConflictValidator:
    def __init__(
        self,
        *,
        gateway: CalendarConflictGateway,
        now_ms: Callable[[], int],
        work_hours_provider: Callable[[], CalendarWorkHours],
    ) -> None:
        self._gateway = gateway
        self._now_ms = now_ms
        self._work_hours_provider = work_hours_provider

    def fresh_risk(self, arguments: Mapping[str, object]) -> dict[str, object]:
        effective_arguments = dict(arguments)
        if _needs_existing_update_interval(effective_arguments):
            calendar_id = _required_text(effective_arguments.get("calendar_id"), "calendar_id")
            event_id = _required_text(effective_arguments.get("event_id"), "event_id")
            target = self._gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
            if (
                target.resource_type is not ResourceType.CALENDAR_EVENT
                or target.parent_id != calendar_id
                or target.resource_id != event_id
            ):
                raise PolicyViolationError(
                    "calendar update target does not match the requested event"
                )
            effective_arguments = _with_existing_interval(effective_arguments, target.payload)
        calendar_id, proposed, excluded_event_id = calendar_conflict_input(
            effective_arguments, timezone=self._work_hours_provider().timezone
        )
        time_range = TimeRange(
            start=proposed.start.isoformat(),
            end=proposed.end.isoformat(),
        )
        events: list[CalendarEventCandidate] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page = self._gateway.list_calendar_events(
                calendar_id=calendar_id,
                page_token=page_token,
                page_size=CALENDAR_CONFLICT_PAGE_SIZE,
                time_min=time_range.start,
                time_max=time_range.end,
                single_events=True,
                order_by="startTime",
            )
            events.extend(
                _event_candidate(
                    item, calendar_id=calendar_id, timezone=self._work_hours_provider().timezone
                )
                for item in page.items
            )
            next_token = page.next_page_token
            if next_token is None:
                break
            if next_token == page_token or next_token in seen_tokens:
                raise PolicyViolationError("calendar conflict pagination token cycle detected")
            seen_tokens.add(next_token)
            page_token = next_token
        calendars = self._gateway.query_freebusy(calendar_ids=(calendar_id,), time_range=time_range)
        freebusy = _freebusy_intervals(calendars, calendar_id=calendar_id)
        freebusy = _residual_freebusy(freebusy, events=tuple(events))
        return evaluate_calendar_conflict(
            proposed=proposed,
            events=tuple(events),
            freebusy=freebusy,
            work_hours=self._work_hours_provider(),
            excluded_event_id=excluded_event_id,
        ).as_risk(
            checked_at_ms=self._now_ms(),
            freshness=CalendarConflictFreshness.FRESH_GOOGLE_GET,
        )


def evidence_calendar_conflict_risk(
    *,
    arguments: Mapping[str, object],
    acquisition_result: Mapping[str, object],
    checked_at_ms: int,
    work_hours: CalendarWorkHours,
) -> dict[str, object]:
    summaries = acquisition_result.get("source_summaries")
    if not isinstance(summaries, list):
        return {}
    found_calendar = False
    events: list[CalendarEventCandidate] = []
    freebusy: list[CalendarInterval] = []
    effective_arguments = dict(arguments)
    requested_calendar_id = _required_text(arguments.get("calendar_id"), "calendar_id")
    requested_event_id = arguments.get("event_id")
    for summary in summaries:
        if not isinstance(summary, dict) or str(summary.get("source", "")).upper() != "CALENDAR":
            continue
        found_calendar = True
        resources = summary.get("resources")
        if not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict) or resource.get("parent_id") != requested_calendar_id:
                continue
            payload = resource.get("payload")
            if not isinstance(payload, dict):
                continue
            resource_type = resource.get("resource_type")
            if resource_type == ResourceType.CALENDAR_EVENT.value:
                if (
                    requested_event_id is not None
                    and resource.get("resource_id") == requested_event_id
                    and _needs_existing_update_interval(effective_arguments)
                ):
                    effective_arguments = _with_existing_interval(effective_arguments, payload)
                events.append(
                    _event_candidate_from_values(
                        event_id=_required_text(resource.get("resource_id"), "calendar event id"),
                        calendar_id=requested_calendar_id,
                        payload=payload,
                        timezone=work_hours.timezone,
                    )
                )
            elif resource_type == ResourceType.CALENDAR_FREEBUSY.value:
                freebusy.extend(_freebusy_payload_intervals(payload))
    if not found_calendar:
        return {}
    if _needs_existing_update_interval(effective_arguments):
        return {}
    calendar_id, proposed, excluded_event_id = calendar_conflict_input(
        effective_arguments, timezone=work_hours.timezone
    )
    return evaluate_calendar_conflict(
        proposed=proposed,
        events=tuple(events),
        freebusy=_residual_freebusy(
            tuple(freebusy),
            events=tuple(events),
        ),
        work_hours=work_hours,
        excluded_event_id=excluded_event_id,
    ).as_risk(
        checked_at_ms=checked_at_ms,
        freshness=CalendarConflictFreshness.EVIDENCE_ONLY,
    )


def calendar_conflict_input(
    arguments: Mapping[str, object], *, timezone: str
) -> tuple[str, CalendarInterval, str | None]:
    calendar_id = _required_text(arguments.get("calendar_id"), "calendar_id")
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        raise PolicyViolationError("calendar write requires payload")
    proposed = CalendarInterval(
        start=_parse_calendar_datetime(payload.get("start"), timezone=timezone),
        end=_parse_calendar_datetime(payload.get("end"), timezone=timezone),
    )
    event_id = arguments.get("event_id")
    if event_id is not None and not isinstance(event_id, str):
        raise PolicyViolationError("calendar event_id must be a string")
    return calendar_id, proposed, cast(str | None, event_id)


def merge_calendar_conflict_risk(
    current_risk: Mapping[str, object], conflict_risk: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(current_risk)
    value = conflict_risk.get("calendar_conflict")
    if isinstance(value, dict):
        merged["calendar_conflict"] = value
    return normalize_action_risk(merged)


def calendar_conflict_authority(
    risk: Mapping[str, object],
) -> tuple[str, tuple[str, ...]] | None:
    value = risk.get("calendar_conflict")
    if not isinstance(value, dict):
        return None
    decision = value.get("decision")
    matched_ids = value.get("matched_resource_ids")
    if decision not in {item.value for item in CalendarConflictDecision}:
        raise PolicyViolationError("stored calendar conflict decision is invalid")
    if not isinstance(matched_ids, list) or any(not isinstance(item, str) for item in matched_ids):
        raise PolicyViolationError("stored calendar conflict resource ids are invalid")
    return cast(str, decision), tuple(sorted(set(cast(list[str], matched_ids))))


def approval_source_snapshot_for_calendar_conflict(
    *, risk: Mapping[str, object], acknowledged: bool
) -> dict[str, object]:
    value = risk.get("calendar_conflict")
    return {
        "calendar_conflict": {
            "risk": value if isinstance(value, dict) else None,
            "acknowledged": acknowledged,
        }
    }


def approval_calendar_conflict_authority(
    source_snapshot: Mapping[str, object],
) -> tuple[str, tuple[str, ...]] | None:
    snapshot = source_snapshot.get("calendar_conflict")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("risk"), dict):
        return None
    return calendar_conflict_authority({"calendar_conflict": snapshot["risk"]})


def calendar_conflict_change_requires_reapproval(
    *, approved: tuple[str, tuple[str, ...]] | None, current: tuple[str, tuple[str, ...]] | None
) -> bool:
    return current is not None and current != approved


def require_calendar_conflict_acknowledgement(
    *, risk: Mapping[str, object], acknowledged: bool
) -> CalendarConflictDecision | None:
    authority = calendar_conflict_authority(risk)
    if authority is None:
        return None
    decision = CalendarConflictDecision(authority[0])
    if decision is not CalendarConflictDecision.NO_CONFLICT and not acknowledged:
        if decision is CalendarConflictDecision.HARD_CONFLICT:
            raise PolicyViolationError(
                "calendar conflict exists; explicit conflict override is required"
            )
        raise PolicyViolationError("calendar warning requires explicit acknowledgement")
    return decision


def _event_candidate(
    snapshot: ResourceSnapshot, *, calendar_id: str, timezone: str
) -> CalendarEventCandidate:
    if (
        snapshot.resource_type is not ResourceType.CALENDAR_EVENT
        or snapshot.parent_id != calendar_id
    ):
        raise PolicyViolationError("calendar conflict source returned an invalid event")
    return _event_candidate_from_values(
        event_id=snapshot.resource_id,
        calendar_id=calendar_id,
        payload=snapshot.payload,
        timezone=timezone,
    )


def calendar_event_candidate(
    snapshot: ResourceSnapshot, *, calendar_id: str, timezone: str
) -> CalendarEventCandidate:
    """Normalize one Calendar Event through the shared FN-032 boundary."""

    return _event_candidate(snapshot, calendar_id=calendar_id, timezone=timezone)


def calendar_event_candidate_from_values(
    *, event_id: str, calendar_id: str, payload: Mapping[str, object], timezone: str
) -> CalendarEventCandidate:
    return _event_candidate_from_values(
        event_id=event_id,
        calendar_id=calendar_id,
        payload=payload,
        timezone=timezone,
    )


def _event_candidate_from_values(
    *, event_id: str, calendar_id: str, payload: Mapping[str, object], timezone: str
) -> CalendarEventCandidate:
    return CalendarEventCandidate(
        event_id=event_id,
        calendar_id=calendar_id,
        interval=CalendarInterval(
            start=_parse_calendar_datetime(payload.get("start"), timezone=timezone),
            end=_parse_calendar_datetime(payload.get("end"), timezone=timezone),
        ),
        transparency=_optional_text(payload.get("transparency")),
        event_type=_optional_text(payload.get("event_kind")),
        status=_optional_text(payload.get("status")),
        self_response_status=_optional_text(payload.get("self_response_status")),
    )


def _freebusy_intervals(
    calendars: tuple[FreeBusyCalendar, ...], *, calendar_id: str
) -> tuple[CalendarInterval, ...]:
    if len(calendars) != 1 or calendars[0].calendar_id != calendar_id:
        raise PolicyViolationError("freebusy response does not match requested calendar")
    return tuple(
        CalendarInterval(
            start=_parse_aware_datetime(item.start), end=_parse_aware_datetime(item.end)
        )
        for item in calendars[0].intervals
        if item.transparency.casefold() not in {"transparent", "free"}
    )


def calendar_freebusy_intervals(
    calendars: tuple[FreeBusyCalendar, ...], *, calendar_id: str
) -> tuple[CalendarInterval, ...]:
    return _freebusy_intervals(calendars, calendar_id=calendar_id)


def _freebusy_payload_intervals(payload: Mapping[str, object]) -> list[CalendarInterval]:
    values = payload.get("busy_intervals")
    if not isinstance(values, list):
        return []
    result: list[CalendarInterval] = []
    for value in values:
        if not isinstance(value, dict):
            raise PolicyViolationError("calendar freebusy evidence is malformed")
        transparency = _optional_text(value.get("transparency")) or "opaque"
        if transparency.casefold() in {"transparent", "free"}:
            continue
        result.append(
            CalendarInterval(
                start=_parse_aware_datetime(value.get("start")),
                end=_parse_aware_datetime(value.get("end")),
            )
        )
    return result


def calendar_freebusy_payload_intervals(
    payload: Mapping[str, object],
) -> tuple[CalendarInterval, ...]:
    return tuple(_freebusy_payload_intervals(payload))


def _residual_freebusy(
    freebusy: tuple[CalendarInterval, ...],
    *,
    events: tuple[CalendarEventCandidate, ...],
) -> tuple[CalendarInterval, ...]:
    """Keep only generic busy intervals not explained by Event metadata."""

    known_intervals = {(event.interval.start, event.interval.end) for event in events}
    return tuple(
        interval for interval in freebusy if (interval.start, interval.end) not in known_intervals
    )


def residual_calendar_freebusy(
    freebusy: tuple[CalendarInterval, ...],
    *,
    events: tuple[CalendarEventCandidate, ...],
) -> tuple[CalendarInterval, ...]:
    return _residual_freebusy(freebusy, events=events)


def _parse_calendar_datetime(value: object, *, timezone: str) -> datetime:
    text = _required_text(value, "calendar interval")
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time.min, tzinfo=ZoneInfo(timezone))
    return _parse_aware_datetime(text)


def _parse_aware_datetime(value: object) -> datetime:
    text = _required_text(value, "calendar datetime")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyViolationError("calendar datetime must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyViolationError("calendar datetime must be timezone-aware")
    return parsed


def _needs_existing_update_interval(arguments: Mapping[str, object]) -> bool:
    if not isinstance(arguments.get("event_id"), str):
        return False
    payload = arguments.get("payload")
    return (
        not isinstance(payload, dict)
        or not isinstance(payload.get("start"), str)
        or not isinstance(payload.get("end"), str)
    )


def _with_existing_interval(
    arguments: Mapping[str, object], existing_payload: Mapping[str, object]
) -> dict[str, object]:
    payload = arguments.get("payload")
    merged_payload = dict(payload) if isinstance(payload, dict) else {}
    for field in ("start", "end"):
        if not isinstance(merged_payload.get(field), str):
            merged_payload[field] = existing_payload.get(field)
    return {**arguments, "payload": merged_payload}


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolationError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "CALENDAR_CONFLICT_BUFFER_SECONDS",
    "CALENDAR_CONFLICT_TOOLS",
    "CALENDAR_CREATE_TOOL",
    "CALENDAR_UPDATE_TOOL",
    "CalendarConflictGateway",
    "CalendarConflictValidator",
    "approval_calendar_conflict_authority",
    "approval_source_snapshot_for_calendar_conflict",
    "calendar_conflict_authority",
    "calendar_conflict_change_requires_reapproval",
    "calendar_conflict_input",
    "calendar_event_candidate",
    "calendar_event_candidate_from_values",
    "calendar_freebusy_intervals",
    "calendar_freebusy_payload_intervals",
    "evidence_calendar_conflict_risk",
    "merge_calendar_conflict_risk",
    "require_calendar_conflict_acknowledgement",
    "residual_calendar_freebusy",
]
