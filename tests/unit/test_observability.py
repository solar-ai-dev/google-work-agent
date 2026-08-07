import os
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.application.observability import (
    EventCategory,
    EventValidationError,
    ObservabilityContext,
    SanitizedJsonlLogSink,
    Severity,
    StaticMaintenanceGate,
    create_event_envelope,
    sanitize_event_attributes,
)
from google_work_agent.ports import OperationalLogRecord


def test_sanitize_event_attributes_removes_forbidden_keys_and_redacts_patterns() -> None:
    sanitized = sanitize_event_attributes(
        {
            "authorization": "Bearer CANARY_AUTHORIZATION",
            "nested": {
                "refreshToken": "CANARY_REFRESH_TOKEN",
                "email": "user@example.com",
                "path": r"C:\Users\alice\project",
            },
            "safe": "hello",
        }
    )
    nested = cast(dict[str, object], sanitized.values["nested"])

    assert "authorization" not in sanitized.values
    assert nested["email"] == "<redacted-email>@example.com"
    assert nested["path"] == r"C:\Users\<redacted-user>\project"
    assert sanitized.values["safe"] == "hello"
    assert sanitized.removed_fields


def test_create_event_envelope_rejects_negative_time() -> None:
    with pytest.raises(EventValidationError):
        create_event_envelope(
            event_name="COMMAND_APPLIED",
            event_category=EventCategory.DOMAIN,
            occurred_at_ms=-1,
            severity=Severity.INFO,
            component="answer_only",
            environment="test",
            release_version="dev",
            correlation=ObservabilityContext(run_id="run-1"),
            attributes={},
        )


def test_jsonl_sink_rotates_and_applies_retention(tmp_path: Path) -> None:
    now_state = {"value": 1_000}
    sink = SanitizedJsonlLogSink(
        directory=tmp_path,
        filename_prefix="service",
        now_ms=lambda: now_state["value"],
    )
    envelope = create_event_envelope(
        event_name="COMMAND_APPLIED",
        event_category=EventCategory.DOMAIN,
        occurred_at_ms=1_000,
        severity=Severity.INFO,
        component="answer_only",
        environment="test",
        release_version="dev",
        correlation=ObservabilityContext(run_id="run-1"),
        attributes={"safe": "ok"},
    )
    sink.append(OperationalLogRecord(event_json='{"ok":1}', occurred_at_ms=1_000))
    assert any(path.name == "service.jsonl" for path in tmp_path.iterdir())
    del envelope
    old_file = tmp_path / "service-old.jsonl"
    old_file.write_text('{"old":1}\n', encoding="utf-8")
    old_epoch_seconds = (now_state["value"] - (15 * 24 * 60 * 60 * 1000)) / 1000
    os.utime(old_file, (old_epoch_seconds, old_epoch_seconds))
    now_state["value"] = 1_000 + (15 * 24 * 60 * 60 * 1000)
    sink.append(
        OperationalLogRecord(
            event_json='{"ok":2}',
            occurred_at_ms=now_state["value"],
        )
    )
    assert old_file.exists() is False


def test_static_maintenance_gate_reports_flags() -> None:
    snapshot = StaticMaintenanceGate(
        has_active_write=True,
        migration_running=False,
        restore_running=True,
    ).snapshot()

    assert snapshot.has_active_write is True
    assert snapshot.migration_running is False
    assert snapshot.restore_running is True
