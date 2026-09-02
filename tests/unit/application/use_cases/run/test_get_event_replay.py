"""Negative proof for the removed Run-owned SSE replay authority."""

from pathlib import Path


def test_sse_replay__moved_to__exact_application_owner() -> None:
    root = Path(__file__).resolve().parents[5] / "src/google_work_agent/application/use_cases"
    assert not (root / "run/get_event_replay.py").exists()
    assert (root / "sse_event/list_run_events.py").is_file()
