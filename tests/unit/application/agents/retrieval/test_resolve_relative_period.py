from datetime import datetime
from zoneinfo import ZoneInfo

from google_work_agent.application.agents.retrieval.resolve_relative_period import (
    resolve_relative_period,
)


def _now_ms() -> int:
    return int(datetime(2026, 9, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1_000)


def test_relative_periods__resolve_against_user_local_calendar() -> None:
    constraints = [{"kind": "DATE", "field": "period", "value": ["지난 주"]}]

    result = resolve_relative_period(
        constraints,
        now_ms=_now_ms(),
        timezone="Asia/Seoul",
    )

    assert result == {
        "kind": "TEMPORAL_RANGE",
        "axis": "MESSAGE_TIME",
        "start_local": "2026-08-24T00:00:00",
        "end_local": "2026-08-31T00:00:00",
        "timezone": "Asia/Seoul",
    }


def test_recent__uses_bounded_thirty_day_window_including_today() -> None:
    result = resolve_relative_period(
        [{"kind": "DATE", "field": "period", "value": "최근"}],
        now_ms=_now_ms(),
        timezone="Asia/Seoul",
    )

    assert result is not None
    assert result["start_local"] == "2026-08-06T00:00:00"
    assert result["end_local"] == "2026-09-06T00:00:00"


def test_conflicting_relative_periods__do_not_guess_a_range() -> None:
    assert (
        resolve_relative_period(
            [{"kind": "DATE", "field": "period", "value": ["지난주", "최근"]}],
            now_ms=_now_ms(),
            timezone="Asia/Seoul",
        )
        is None
    )
