import json
import os
from pathlib import Path
from secrets import token_urlsafe
from typing import cast

import pytest

from google_work_agent.application.observability import (
    EventCategory,
    EventValidationError,
    ObservabilityContext,
    SanitizationError,
    SanitizedJsonlLogSink,
    Severity,
    StaticMaintenanceGate,
    create_event_envelope,
    sanitize_event_attributes,
)
from google_work_agent.ports import OperationalLogRecord


def _secret(prefix: str) -> str:
    return f"{prefix}-{token_urlsafe(24)}"


def test_sanitize_event_attributes_removes_secret_keys_independent_of_value() -> None:
    access_token = _secret("access")
    refresh_token = _secret("refresh")
    authorization = f"Bearer {_secret('auth')}"
    cookie = f"session={_secret('cookie')}"
    sanitized = sanitize_event_attributes(
        {
            "provider": {
                "headers": {
                    "Authorization": authorization,
                    "Cookie": cookie,
                },
                "oauth": {
                    "access_token": access_token,
                    "refreshToken": refresh_token,
                },
            },
            "safe": "hello",
        }
    )

    provider = cast(dict[str, object], sanitized.values["provider"])
    headers = cast(dict[str, object], provider["headers"])
    oauth = cast(dict[str, object], provider["oauth"])
    serialized = json.dumps(sanitized.values, sort_keys=True)

    assert "Authorization" not in headers
    assert "Cookie" not in headers
    assert "access_token" not in oauth
    assert "refreshToken" not in oauth
    assert access_token not in serialized
    assert refresh_token not in serialized
    assert authorization not in serialized
    assert cookie not in serialized
    assert sanitized.values["safe"] == "hello"
    assert sanitized.removed_fields


def test_sanitize_event_attributes_preserves_bounded_non_secret_metadata() -> None:
    allowed = {
        "credential_state": "READY",
        "token_expired": True,
        "page_token_present": True,
        "continuation_hash": "sha256:abc123",
        "provider_status_code": 401,
    }

    sanitized = sanitize_event_attributes(allowed)

    assert sanitized.values == allowed
    assert sanitized.removed_fields == ()


def test_sanitize_event_attributes_redacts_email_and_home_path() -> None:
    sanitized = sanitize_event_attributes(
        {
            "nested": {
                "email": "user@example.com",
                "path": r"C:\Users\alice\project",
            },
        }
    )
    nested = cast(dict[str, object], sanitized.values["nested"])

    assert nested["email"] == "<redacted-email>@example.com"
    assert nested["path"] == r"C:\Users\<redacted-user>\project"


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


def test_jsonl_sink_scrubs_direct_raw_secret_payload(tmp_path: Path) -> None:
    access_token = _secret("access")
    refresh_token = _secret("refresh")
    authorization = f"Bearer {_secret('authorization')}"
    sink = SanitizedJsonlLogSink(
        directory=tmp_path,
        filename_prefix="service",
        now_ms=lambda: 1_000,
    )
    raw = {
        "provider": {
            "headers": {"Authorization": authorization},
            "oauth": {
                "access_token": access_token,
                "refreshToken": refresh_token,
            },
        },
        "credential_state": "READY",
        "token_expired": True,
        "page_token_present": True,
        "continuation_hash": "sha256:def456",
        "provider_status_code": 401,
    }

    sink.append(OperationalLogRecord(event_json=json.dumps(raw), occurred_at_ms=1_000))

    persisted = (tmp_path / "service.jsonl").read_text(encoding="utf-8")
    persisted_json = json.loads(persisted)
    assert access_token not in persisted
    assert refresh_token not in persisted
    assert authorization not in persisted
    assert persisted_json["credential_state"] == "READY"
    assert persisted_json["token_expired"] is True
    assert persisted_json["page_token_present"] is True
    assert persisted_json["continuation_hash"] == "sha256:def456"
    assert persisted_json["provider_status_code"] == 401


def test_jsonl_sink_rejects_invalid_json_instead_of_persisting_raw_text(tmp_path: Path) -> None:
    sink = SanitizedJsonlLogSink(
        directory=tmp_path,
        filename_prefix="service",
        now_ms=lambda: 1_000,
    )

    with pytest.raises(SanitizationError):
        sink.append(OperationalLogRecord(event_json="not-json", occurred_at_ms=1_000))

    assert not (tmp_path / "service.jsonl").exists()


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
