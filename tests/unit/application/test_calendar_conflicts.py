from __future__ import annotations

import pytest

from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CalendarConflictValidator,
    approval_calendar_conflict_authority,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_change_requires_reapproval,
    evidence_calendar_conflict_risk,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    FreeBusyInterval,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)


def event(event_id: str, *, response: str | None = None) -> ResourceSnapshot:
    payload = {
        "start": "2026-08-12T09:30:00+09:00",
        "end": "2026-08-12T10:30:00+09:00",
    }
    if response is not None:
        payload["self_response_status"] = response
    return ResourceSnapshot(
        fixture_snapshot_id=event_id,
        resource_type=ResourceType.CALENDAR_EVENT,
        resource_id=event_id,
        parent_id="primary",
        related_resource_ids=("primary",),
        version="1",
        recovery_fingerprint=None,
        payload=payload,
    )


class Gateway:
    def __init__(self) -> None:
        self.pages = [ResourcePage(items=(event("event-1"),), next_page_token=None)]
        self.calls: list[dict[str, object]] = []

    def list_calendar_events(self, **kwargs: object) -> ResourcePage:
        self.calls.append(dict(kwargs))
        return self.pages.pop(0)

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        assert calendar_id == "primary"
        return event(event_id)

    def query_freebusy(
        self, *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        return (FreeBusyCalendar(calendar_id=calendar_ids[0], intervals=()),)


def arguments(*, event_id: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "calendar_id": "primary",
        "payload": {
            "start": "2026-08-12T09:00:00+09:00",
            "end": "2026-08-12T10:00:00+09:00",
        },
    }
    if event_id is not None:
        result["event_id"] = event_id
    return result


def test_fresh_check_scopes_every_page_to_exact_zero_buffer_interval() -> None:
    gateway = Gateway()
    risk = CalendarConflictValidator(
        gateway=gateway,
        now_ms=lambda: 123,
        work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
    ).fresh_risk(arguments())
    assert gateway.calls == [
        {
            "calendar_id": "primary",
            "page_token": None,
            "page_size": 100,
            "time_min": "2026-08-12T09:00:00+09:00",
            "time_max": "2026-08-12T10:00:00+09:00",
            "single_events": True,
            "order_by": "startTime",
        }
    ]
    assert risk["calendar_conflict"]["freshness"] == "FRESH_GOOGLE_GET"  # type: ignore[index]


def test_tentative_event_matching_freebusy_remains_warning() -> None:
    gateway = Gateway()
    gateway.pages = [
        ResourcePage(items=(event("tentative", response="tentative"),), next_page_token=None)
    ]

    def matching_freebusy(
        *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        del time_range
        return (
            FreeBusyCalendar(
                calendar_id=calendar_ids[0],
                intervals=(
                    FreeBusyInterval(
                        start="2026-08-12T09:30:00+09:00",
                        end="2026-08-12T10:30:00+09:00",
                        transparency="opaque",
                    ),
                ),
            ),
        )

    gateway.query_freebusy = matching_freebusy  # type: ignore[method-assign]
    risk = CalendarConflictValidator(
        gateway=gateway,
        now_ms=lambda: 123,
        work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
    ).fresh_risk(arguments())

    assert risk["calendar_conflict"]["decision"] == "WARNING"  # type: ignore[index]


def test_update_self_exclusion_keeps_same_time_other_event_hard() -> None:
    gateway = Gateway()
    gateway.pages = [ResourcePage(items=(event("target"), event("other")), next_page_token=None)]

    def matching_freebusy(
        *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        del time_range
        return (
            FreeBusyCalendar(
                calendar_id=calendar_ids[0],
                intervals=(
                    FreeBusyInterval(
                        start="2026-08-12T09:30:00+09:00",
                        end="2026-08-12T10:30:00+09:00",
                        transparency="opaque",
                    ),
                ),
            ),
        )

    gateway.query_freebusy = matching_freebusy  # type: ignore[method-assign]
    risk = CalendarConflictValidator(
        gateway=gateway,
        now_ms=lambda: 123,
        work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
    ).fresh_risk(arguments(event_id="target"))

    assert risk["calendar_conflict"]["decision"] == "HARD_CONFLICT"  # type: ignore[index]
    assert risk["calendar_conflict"]["matched_resource_ids"] == ["other"]  # type: ignore[index]


def test_pagination_cycle_fails_closed() -> None:
    gateway = Gateway()
    gateway.pages = [ResourcePage(items=(), next_page_token="repeat")] * 2
    validator = CalendarConflictValidator(
        gateway=gateway,
        now_ms=lambda: 123,
        work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
    )
    try:
        validator.fresh_risk(arguments())
    except PolicyViolationError as error:
        assert "cycle" in str(error)
    else:
        raise AssertionError("pagination cycle must fail closed")


def test_evidence_check_omits_risk_without_calendar_source() -> None:
    assert (
        evidence_calendar_conflict_risk(
            arguments=arguments(),
            acquisition_result={"source_summaries": []},
            checked_at_ms=123,
            work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
        )
        == {}
    )


def test_evidence_check_uses_current_run_calendar_resources_only() -> None:
    snapshot = event("event-1")
    risk = evidence_calendar_conflict_risk(
        arguments=arguments(),
        acquisition_result={
            "source_summaries": [
                {
                    "source": "CALENDAR",
                    "resources": [
                        {
                            "resource_type": snapshot.resource_type.value,
                            "resource_id": snapshot.resource_id,
                            "parent_id": snapshot.parent_id,
                            "payload": snapshot.payload,
                        }
                    ],
                }
            ]
        },
        checked_at_ms=123,
        work_hours=CalendarWorkHours(timezone="Asia/Seoul"),
    )
    assert risk["calendar_conflict"]["decision"] == "HARD_CONFLICT"  # type: ignore[index]
    assert risk["calendar_conflict"]["freshness"] == "EVIDENCE_ONLY"  # type: ignore[index]


def conflict_risk(decision: str, *matched_ids: str) -> dict[str, object]:
    return {
        "calendar_conflict": {
            "decision": decision,
            "matched_resource_ids": list(matched_ids),
            "reason_codes": ["NO_CONFLICT"],
            "checked_at_ms": 123,
            "freshness": "EVIDENCE_ONLY",
        }
    }


def test_no_conflict_approval_needs_no_acknowledgement() -> None:
    decision = require_calendar_conflict_acknowledgement(
        risk=conflict_risk("NO_CONFLICT"), acknowledged=False
    )
    assert decision is not None and decision.value == "NO_CONFLICT"


def test_warning_approval_requires_acknowledgement() -> None:
    with pytest.raises(PolicyViolationError, match="acknowledgement"):
        require_calendar_conflict_acknowledgement(risk=conflict_risk("WARNING"), acknowledged=False)
    assert require_calendar_conflict_acknowledgement(
        risk=conflict_risk("WARNING"), acknowledged=True
    )


def test_hard_conflict_approval_requires_explicit_override() -> None:
    with pytest.raises(PolicyViolationError, match="override"):
        require_calendar_conflict_acknowledgement(
            risk=conflict_risk("HARD_CONFLICT", "event-1"), acknowledged=False
        )
    assert require_calendar_conflict_acknowledgement(
        risk=conflict_risk("HARD_CONFLICT", "event-1"), acknowledged=True
    )


def test_server_owned_approval_snapshot_contains_risk_and_boolean_only() -> None:
    snapshot = approval_source_snapshot_for_calendar_conflict(
        risk=conflict_risk("HARD_CONFLICT", "event-1"), acknowledged=True
    )
    assert approval_calendar_conflict_authority(snapshot) == (
        "HARD_CONFLICT",
        ("event-1",),
    )
    assert snapshot["calendar_conflict"]["acknowledged"] is True  # type: ignore[index]


@pytest.mark.parametrize(
    ("approved", "current", "expected"),
    [
        (("NO_CONFLICT", ()), ("NO_CONFLICT", ()), False),
        (("NO_CONFLICT", ()), ("WARNING", ()), True),
        (("HARD_CONFLICT", ("a",)), ("HARD_CONFLICT", ("a",)), False),
        (("HARD_CONFLICT", ("a",)), ("HARD_CONFLICT", ("b",)), True),
    ],
)
def test_changed_decision_or_match_set_requires_reapproval(
    approved: tuple[str, tuple[str, ...]],
    current: tuple[str, tuple[str, ...]],
    expected: bool,
) -> None:
    assert (
        calendar_conflict_change_requires_reapproval(approved=approved, current=current) is expected
    )
