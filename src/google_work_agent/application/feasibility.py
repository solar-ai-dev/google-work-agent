"""Deterministic business-deadline feasibility application boundary (FN-033)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_PAGE_SIZE,
    CALENDAR_CONFLICT_TOOLS,
    calendar_event_candidate,
    calendar_event_candidate_from_values,
    calendar_freebusy_intervals,
    calendar_freebusy_payload_intervals,
    residual_calendar_freebusy,
)
from google_work_agent.application.policy_kernels.calendar_conflict import (
    CalendarEventCandidate,
    CalendarInterval,
    CalendarIntervalKind,
    CalendarWorkHours,
    classify_calendar_event,
)
from google_work_agent.application.policy_kernels.feasibility import (
    FeasibilityDecision,
    FeasibilityFreshness,
    derive_deadline_cutoff,
    evaluate_feasibility,
)
from google_work_agent.domain.action.model import PolicyViolationError, normalize_action_risk
from google_work_agent.ports import FreeBusyCalendar, ResourcePage, ResourceType, TimeRange

FEASIBILITY_TOOLS = CALENDAR_CONFLICT_TOOLS


class FeasibilityGateway(Protocol):
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


class FeasibilityValidator:
    def __init__(
        self,
        *,
        gateway: FeasibilityGateway,
        now_ms: Callable[[], int],
        work_hours_provider: Callable[[], CalendarWorkHours],
    ) -> None:
        self._gateway = gateway
        self._now_ms = now_ms
        self._work_hours_provider = work_hours_provider

    def fresh_risk(
        self, *, arguments: Mapping[str, object], risk: Mapping[str, object]
    ) -> dict[str, object]:
        feasibility_input = feasibility_input_from_risk(risk)
        if feasibility_input is None:
            return {}
        work_hours = self._work_hours_provider()
        now_ms = self._now_ms()
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        cutoff = derive_deadline_cutoff(
            cast(str, feasibility_input["business_deadline"]), work_hours=work_hours
        )
        result: dict[str, object] = {"feasibility_input": feasibility_input}
        if cutoff <= now:
            result.update(
                _evaluate(
                    arguments=arguments,
                    feasibility_input=feasibility_input,
                    events=(),
                    freebusy=(),
                    now=now,
                    checked_at_ms=now_ms,
                    freshness=FeasibilityFreshness.FRESH_GOOGLE_GET,
                    work_hours=work_hours,
                )
            )
            return normalize_action_risk(result)
        calendar_id = _required_text(arguments.get("calendar_id"), "calendar_id")
        time_range = TimeRange(start=now.isoformat(), end=cutoff.isoformat())
        events = self._list_all_events(
            calendar_id=calendar_id,
            time_range=time_range,
            timezone=work_hours.timezone,
        )
        calendars = self._gateway.query_freebusy(calendar_ids=(calendar_id,), time_range=time_range)
        freebusy = residual_calendar_freebusy(
            calendar_freebusy_intervals(calendars, calendar_id=calendar_id), events=events
        )
        result.update(
            _evaluate(
                arguments=arguments,
                feasibility_input=feasibility_input,
                events=events,
                freebusy=freebusy,
                now=now,
                checked_at_ms=now_ms,
                freshness=FeasibilityFreshness.FRESH_GOOGLE_GET,
                work_hours=work_hours,
            )
        )
        return normalize_action_risk(result)

    def _list_all_events(
        self, *, calendar_id: str, time_range: TimeRange, timezone: str
    ) -> tuple[CalendarEventCandidate, ...]:
        result: list[CalendarEventCandidate] = []
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
            result.extend(
                calendar_event_candidate(item, calendar_id=calendar_id, timezone=timezone)
                for item in page.items
            )
            next_token = page.next_page_token
            if next_token is None:
                return tuple(result)
            if next_token == page_token or next_token in seen_tokens:
                raise PolicyViolationError("feasibility pagination token cycle detected")
            seen_tokens.add(next_token)
            page_token = next_token


def build_feasibility_input(
    *, analysis_result: Mapping[str, object], arguments: Mapping[str, object]
) -> dict[str, object] | None:
    constraints = analysis_result.get("schedule_constraints")
    if not isinstance(constraints, dict):
        return None
    deadline = _required_text(constraints.get("business_deadline"), "business_deadline")
    deadline_source = constraints.get("business_deadline_source")
    if deadline_source not in {"USER", "GMAIL_EVIDENCE"}:
        raise PolicyViolationError("business deadline source is invalid")
    duration_source = constraints.get("duration_source")
    duration = constraints.get("expected_duration_minutes")
    if duration_source == "EVENT_INTERVAL":
        duration = _event_duration_minutes(arguments)
    elif duration_source != "EXPLICIT_ESTIMATE":
        raise PolicyViolationError("expected duration source is invalid")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise PolicyViolationError("expected duration must be confirmed before planning")
    return {
        "business_deadline": deadline,
        "business_deadline_source": deadline_source,
        "required_duration_minutes": duration,
        "duration_source": duration_source,
    }


def evidence_feasibility_risk(
    *,
    arguments: Mapping[str, object],
    analysis_result: Mapping[str, object],
    acquisition_result: Mapping[str, object],
    checked_at_ms: int,
    work_hours: CalendarWorkHours,
) -> dict[str, object]:
    feasibility_input = build_feasibility_input(
        analysis_result=analysis_result, arguments=arguments
    )
    if feasibility_input is None:
        return {}
    result: dict[str, object] = {"feasibility_input": feasibility_input}
    now = datetime.fromtimestamp(checked_at_ms / 1000, UTC)
    cutoff = derive_deadline_cutoff(
        cast(str, feasibility_input["business_deadline"]), work_hours=work_hours
    )
    if cutoff <= now:
        result.update(
            _evaluate(
                arguments=arguments,
                feasibility_input=feasibility_input,
                events=(),
                freebusy=(),
                now=now,
                checked_at_ms=checked_at_ms,
                freshness=FeasibilityFreshness.EVIDENCE_ONLY,
                work_hours=work_hours,
            )
        )
        return normalize_action_risk(result)
    calendar_id = _required_text(arguments.get("calendar_id"), "calendar_id")
    evidence = _evidence_calendar_inputs(
        acquisition_result=acquisition_result,
        calendar_id=calendar_id,
        timezone=work_hours.timezone,
        now=now,
        cutoff=cutoff,
    )
    if evidence is None:
        return normalize_action_risk(result)
    events, freebusy = evidence
    result.update(
        _evaluate(
            arguments=arguments,
            feasibility_input=feasibility_input,
            events=events,
            freebusy=freebusy,
            now=now,
            checked_at_ms=checked_at_ms,
            freshness=FeasibilityFreshness.EVIDENCE_ONLY,
            work_hours=work_hours,
        )
    )
    return normalize_action_risk(result)


def merge_feasibility_risk(
    current_risk: Mapping[str, object], fresh_risk: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(current_risk)
    if isinstance(fresh_risk.get("feasibility_input"), dict):
        merged["feasibility_input"] = fresh_risk["feasibility_input"]
    if isinstance(fresh_risk.get("feasibility"), dict):
        merged["feasibility"] = fresh_risk["feasibility"]
    return normalize_action_risk(merged)


def refresh_feasibility_input_for_arguments(
    *, risk: Mapping[str, object], arguments: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(risk)
    feasibility_input = feasibility_input_from_risk(risk)
    if feasibility_input is None:
        return normalize_action_risk(merged)
    if feasibility_input.get("duration_source") == "EVENT_INTERVAL":
        feasibility_input["required_duration_minutes"] = _event_duration_minutes(arguments)
    merged["feasibility_input"] = feasibility_input
    return normalize_action_risk(merged)


def feasibility_input_from_risk(risk: Mapping[str, object]) -> dict[str, object] | None:
    value = risk.get("feasibility_input")
    return dict(value) if isinstance(value, dict) else None


def feasibility_authority(risk: Mapping[str, object]) -> tuple[object, ...] | None:
    value = risk.get("feasibility")
    if not isinstance(value, dict):
        return None
    decision = value.get("decision")
    if decision not in {item.value for item in FeasibilityDecision}:
        raise PolicyViolationError("stored feasibility decision is invalid")
    return (
        decision,
        tuple(value.get("reason_codes", [])) if isinstance(value.get("reason_codes"), list) else (),
        value.get("business_deadline"),
        value.get("derived_cutoff"),
        value.get("required_duration_minutes"),
        value.get("best_clean_slot_minutes"),
        value.get("best_warning_slot_minutes"),
    )


def approval_source_snapshot_for_feasibility(*, risk: Mapping[str, object]) -> dict[str, object]:
    value = risk.get("feasibility")
    return {"feasibility": value if isinstance(value, dict) else None}


def approval_feasibility_authority(
    source_snapshot: Mapping[str, object],
) -> tuple[object, ...] | None:
    value = source_snapshot.get("feasibility")
    return feasibility_authority({"feasibility": value}) if isinstance(value, dict) else None


def feasibility_change_requires_reapproval(
    *, approved: tuple[object, ...] | None, current: tuple[object, ...] | None
) -> bool:
    return current != approved


def require_feasibility_approval(risk: Mapping[str, object]) -> FeasibilityDecision | None:
    authority = feasibility_authority(risk)
    if authority is None:
        return None
    decision = FeasibilityDecision(cast(str, authority[0]))
    if decision is FeasibilityDecision.INFEASIBLE:
        raise PolicyViolationError("work is infeasible before the business deadline")
    return decision


def _evidence_calendar_inputs(
    *,
    acquisition_result: Mapping[str, object],
    calendar_id: str,
    timezone: str,
    now: datetime,
    cutoff: datetime,
) -> tuple[tuple[CalendarEventCandidate, ...], tuple[CalendarInterval, ...]] | None:
    summaries = acquisition_result.get("source_summaries")
    if not isinstance(summaries, list):
        return None
    events: list[CalendarEventCandidate] = []
    freebusy: list[CalendarInterval] = []
    has_full_coverage = False
    for summary in summaries:
        if not isinstance(summary, dict) or str(summary.get("source", "")).upper() != "CALENDAR":
            continue
        resources = summary.get("resources")
        if not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict) or resource.get("parent_id") != calendar_id:
                continue
            payload = resource.get("payload")
            if not isinstance(payload, dict):
                continue
            if resource.get("resource_type") == ResourceType.CALENDAR_EVENT.value:
                events.append(
                    calendar_event_candidate_from_values(
                        event_id=_required_text(resource.get("resource_id"), "calendar event id"),
                        calendar_id=calendar_id,
                        payload=payload,
                        timezone=timezone,
                    )
                )
            elif resource.get("resource_type") == ResourceType.CALENDAR_FREEBUSY.value:
                freebusy.extend(calendar_freebusy_payload_intervals(payload))
                time_min = _parse_aware(payload.get("time_min"))
                time_max = _parse_aware(payload.get("time_max"))
                has_full_coverage = has_full_coverage or (time_min <= now and time_max >= cutoff)
    if not has_full_coverage:
        return None
    event_tuple = tuple(events)
    return event_tuple, residual_calendar_freebusy(tuple(freebusy), events=event_tuple)


def _evaluate(
    *,
    arguments: Mapping[str, object],
    feasibility_input: Mapping[str, object],
    events: tuple[CalendarEventCandidate, ...],
    freebusy: tuple[CalendarInterval, ...],
    now: datetime,
    checked_at_ms: int,
    freshness: FeasibilityFreshness,
    work_hours: CalendarWorkHours,
) -> dict[str, object]:
    excluded_id = arguments.get("event_id") if isinstance(arguments.get("event_id"), str) else None
    hard: list[CalendarInterval] = list(freebusy)
    warning: list[CalendarInterval] = []
    for event in events:
        if event.event_id == excluded_id:
            continue
        kind = classify_calendar_event(event)
        if kind is CalendarIntervalKind.HARD:
            hard.append(event.interval)
        elif kind is CalendarIntervalKind.WARNING:
            warning.append(event.interval)
    return evaluate_feasibility(
        now=now,
        business_deadline=cast(str, feasibility_input["business_deadline"]),
        required_duration_minutes=cast(int, feasibility_input["required_duration_minutes"]),
        work_hours=work_hours,
        hard_busy=tuple(hard),
        warning_busy=tuple(warning),
    ).as_risk(checked_at_ms=checked_at_ms, freshness=freshness)


def _event_duration_minutes(arguments: Mapping[str, object]) -> int:
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        raise PolicyViolationError("calendar write requires payload")
    start = _parse_aware(payload.get("start"))
    end = _parse_aware(payload.get("end"))
    minutes = int((end - start).total_seconds() // 60)
    if minutes <= 0:
        raise PolicyViolationError("calendar event interval must be positive")
    return minutes


def _parse_aware(value: object) -> datetime:
    text = _required_text(value, "calendar datetime")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyViolationError("calendar datetime must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyViolationError("calendar datetime must be timezone-aware")
    return parsed


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolationError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "FEASIBILITY_TOOLS",
    "FeasibilityGateway",
    "FeasibilityValidator",
    "approval_feasibility_authority",
    "approval_source_snapshot_for_feasibility",
    "build_feasibility_input",
    "evidence_feasibility_risk",
    "feasibility_authority",
    "feasibility_change_requires_reapproval",
    "feasibility_input_from_risk",
    "merge_feasibility_risk",
    "refresh_feasibility_input_for_arguments",
    "require_feasibility_approval",
]
