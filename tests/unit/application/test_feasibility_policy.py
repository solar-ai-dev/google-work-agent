from __future__ import annotations

from datetime import datetime

import pytest

from google_work_agent.application.feasibility import (
    FeasibilityValidator,
    evidence_feasibility_risk,
    feasibility_change_requires_reapproval,
    merge_feasibility_risk,
    refresh_feasibility_input_for_arguments,
    require_feasibility_approval,
)
from google_work_agent.application.policy_kernels.calendar_conflict import CalendarWorkHours
from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.ports import (
    FreeBusyCalendar,
    ResourcePage,
    ResourceType,
    TimeRange,
)

NOW = datetime.fromisoformat("2026-08-12T09:00:00+09:00")
NOW_MS = int(NOW.timestamp() * 1000)
WORK_HOURS = CalendarWorkHours(timezone="Asia/Seoul")


class Gateway:
    def __init__(self) -> None:
        self.pages = [ResourcePage(items=(), next_page_token=None)]
        self.calls: list[dict[str, object]] = []

    def list_calendar_events(self, **kwargs: object) -> ResourcePage:
        self.calls.append(dict(kwargs))
        return self.pages.pop(0)

    def query_freebusy(
        self, *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        self.calls.append({"calendar_ids": calendar_ids, "time_range": time_range})
        return (FreeBusyCalendar(calendar_id=calendar_ids[0], intervals=()),)


def _arguments(*, end: str = "2026-08-12T11:00:00+09:00") -> dict[str, object]:
    return {
        "calendar_id": "primary",
        "payload": {"start": "2026-08-12T09:00:00+09:00", "end": end},
    }


def _analysis(*, duration: int | None = 120, source: str = "USER") -> dict[str, object]:
    return {
        "schedule_constraints": {
            "business_deadline": "2026-08-12",
            "business_deadline_source": source,
            "expected_duration_minutes": duration,
            "duration_source": "EXPLICIT_ESTIMATE",
        }
    }


def _input_risk() -> dict[str, object]:
    return {
        "feasibility_input": {
            "business_deadline": "2026-08-12",
            "business_deadline_source": "USER",
            "required_duration_minutes": 120,
            "duration_source": "EXPLICIT_ESTIMATE",
        }
    }


def test_check1_uses_complete_evidence_horizon() -> None:
    risk = evidence_feasibility_risk(
        arguments=_arguments(),
        analysis_result=_analysis(),
        acquisition_result={
            "source_summaries": [
                {
                    "source": "CALENDAR",
                    "resources": [
                        {
                            "resource_type": ResourceType.CALENDAR_FREEBUSY.value,
                            "resource_id": "freebusy",
                            "parent_id": "primary",
                            "payload": {
                                "time_min": NOW.isoformat(),
                                "time_max": "2026-08-12T18:00:00+09:00",
                                "busy_intervals": [],
                            },
                        }
                    ],
                }
            ]
        },
        checked_at_ms=NOW_MS,
        work_hours=WORK_HOURS,
    )
    assert risk["feasibility"]["decision"] == "FEASIBLE"  # type: ignore[index]
    assert risk["feasibility"]["freshness"] == "EVIDENCE_ONLY"  # type: ignore[index]


def test_check1_incomplete_calendar_coverage_never_fakes_feasible() -> None:
    risk = evidence_feasibility_risk(
        arguments=_arguments(),
        analysis_result=_analysis(),
        acquisition_result={"source_summaries": []},
        checked_at_ms=NOW_MS,
        work_hours=WORK_HOURS,
    )
    assert "feasibility_input" in risk
    assert "feasibility" not in risk


def test_event_interval_is_the_only_deterministic_duration_fallback() -> None:
    analysis = _analysis(duration=None)
    constraints = analysis["schedule_constraints"]
    assert isinstance(constraints, dict)
    constraints["duration_source"] = "EVENT_INTERVAL"
    risk = evidence_feasibility_risk(
        arguments=_arguments(),
        analysis_result=analysis,
        acquisition_result={"source_summaries": []},
        checked_at_ms=NOW_MS,
        work_hours=WORK_HOURS,
    )
    assert risk["feasibility_input"]["required_duration_minutes"] == 120  # type: ignore[index]


def test_fresh_check_reads_exact_deadline_horizon() -> None:
    gateway = Gateway()
    risk = FeasibilityValidator(
        gateway=gateway,
        now_ms=lambda: NOW_MS,
        work_hours_provider=lambda: WORK_HOURS,
    ).fresh_risk(arguments=_arguments(), risk=_input_risk())
    assert risk["feasibility"]["decision"] == "FEASIBLE"  # type: ignore[index]
    assert gateway.calls[0]["time_min"] == "2026-08-12T00:00:00+00:00"
    assert gateway.calls[0]["time_max"] == "2026-08-12T18:00:00+09:00"


def test_pagination_cycle_and_read_failure_fail_closed() -> None:
    gateway = Gateway()
    gateway.pages = [ResourcePage(items=(), next_page_token="repeat")] * 2
    validator = FeasibilityValidator(
        gateway=gateway,
        now_ms=lambda: NOW_MS,
        work_hours_provider=lambda: WORK_HOURS,
    )
    with pytest.raises(PolicyViolationError, match="cycle"):
        validator.fresh_risk(arguments=_arguments(), risk=_input_risk())


@pytest.mark.parametrize("failure_point", ["events", "freebusy"])
def test_each_fresh_calendar_read_failure_is_propagated(failure_point: str) -> None:
    gateway = Gateway()
    if failure_point == "events":

        def fail_events(**kwargs: object) -> ResourcePage:
            del kwargs
            raise TimeoutError("events unavailable")

        gateway.list_calendar_events = fail_events  # type: ignore[method-assign]
    else:

        def fail_freebusy(
            *, calendar_ids: tuple[str, ...], time_range: TimeRange
        ) -> tuple[FreeBusyCalendar, ...]:
            del calendar_ids, time_range
            raise TimeoutError("freebusy unavailable")

        gateway.query_freebusy = fail_freebusy  # type: ignore[method-assign]
    validator = FeasibilityValidator(
        gateway=gateway,
        now_ms=lambda: NOW_MS,
        work_hours_provider=lambda: WORK_HOURS,
    )
    with pytest.raises(TimeoutError, match="unavailable"):
        validator.fresh_risk(arguments=_arguments(), risk=_input_risk())


def test_infeasible_blocks_approval_and_changed_authority_requires_reapproval() -> None:
    risk = {
        "feasibility": {
            "decision": "INFEASIBLE",
            "reason_codes": ["NO_CONTIGUOUS_SLOT"],
            "business_deadline": "2026-08-12",
            "derived_cutoff": "2026-08-12T18:00:00+09:00",
            "required_duration_minutes": 120,
            "best_clean_slot_minutes": 60,
            "best_warning_slot_minutes": 60,
        }
    }
    with pytest.raises(PolicyViolationError, match="infeasible"):
        require_feasibility_approval(risk)
    assert feasibility_change_requires_reapproval(approved=("FEASIBLE",), current=("RISK",))


def test_modify_rederives_event_duration_and_preserves_other_server_risks() -> None:
    current = {
        "duplicate": {"decision": "NOT_DUPLICATE"},
        "calendar_conflict": {"decision": "NO_CONFLICT"},
        "feasibility_input": {
            "business_deadline": "2026-08-12",
            "business_deadline_source": "USER",
            "required_duration_minutes": 120,
            "duration_source": "EVENT_INTERVAL",
        },
        "feasibility": {"decision": "FEASIBLE"},
    }
    refreshed_input = refresh_feasibility_input_for_arguments(
        risk=current, arguments=_arguments(end="2026-08-12T10:00:00+09:00")
    )
    merged = merge_feasibility_risk(
        refreshed_input,
        {
            "feasibility_input": refreshed_input["feasibility_input"],
            "feasibility": {"decision": "RISK"},
        },
    )
    assert merged["feasibility_input"]["required_duration_minutes"] == 60  # type: ignore[index]
    assert merged["duplicate"] == current["duplicate"]
    assert merged["calendar_conflict"] == current["calendar_conflict"]
    assert merged["feasibility"] == {"decision": "RISK"}
