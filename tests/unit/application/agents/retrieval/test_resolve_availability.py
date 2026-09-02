from google_work_agent.application.agents.retrieval.resolve_availability import (
    resolve_availability,
)


def test_resolve_availability__merges_busy_intervals__and_subtracts_window() -> None:
    result = resolve_availability(
        window_start="2026-08-30T09:00:00+09:00",
        window_end="2026-08-30T13:00:00+09:00",
        timezone="Asia/Seoul",
        busy_intervals=[
            {
                "start": "2026-08-30T10:00:00+09:00",
                "end": "2026-08-30T11:00:00+09:00",
                "resource_ref": "e1",
            },
            {
                "start": "2026-08-30T10:30:00+09:00",
                "end": "2026-08-30T12:00:00+09:00",
                "resource_ref": "e2",
            },
        ],
    )

    assert [(item["start"][11:16], item["end"][11:16]) for item in result] == [
        ("09:00", "10:00"),
        ("12:00", "13:00"),
    ]
    assert result[0]["derived_from_resource_refs"] == ["e1", "e2"]
