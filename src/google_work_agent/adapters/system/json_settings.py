"""Canonical settings schema validation and atomic JSON storage."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from threading import RLock
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)
from google_work_agent.ports.system.settings_port import (
    PanelPreferencesV1,
    SettingsPatchV1,
    SettingsPort,
    SettingsViewV1,
)

_MAX_SETTINGS_BYTES = 32 * 1024
_SETTINGS_FIELDS = frozenset(SettingsViewV1.__dataclass_fields__)
_PATCH_FIELDS = frozenset(SettingsPatchV1.__dataclass_fields__) - {"schema_version"}


def _default_settings() -> SettingsViewV1:
    return SettingsViewV1(
        schema_version=1,
        timezone="Asia/Seoul",
        default_tasklist_id=None,
        default_calendar_id=None,
        preferred_llm_mode="AUTO",
        external_llm_consent=False,
        retention_days=30,
        theme="LIGHT",
        panel_preferences=PanelPreferencesV1(1, True, "CONVERSATIONS"),
        working_day_start_local="09:00",
        working_day_end_local="18:00",
        include_weekends=False,
        calendar_buffer_minutes=0,
        max_run_execution_ms=900_000,
        max_connector_calls_per_run=50,
        max_source_page_calls_per_run=20,
        max_detail_fetches_per_run=50,
        max_context_tokens_per_run=16_000,
        max_retry_attempts_per_run=2,
        circuit_failure_threshold=3,
        circuit_open_duration_ms=30_000,
    )


class FileSettingsStore:
    """Own the versioned app-settings.json envelope and atomic replacement."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> tuple[SettingsViewV1, dict[str, str] | None]:
        if not self._path.exists():
            settings = _default_settings()
            self.save(settings, marker=None)
            return settings, None
        raw = self._path.read_bytes()
        if len(raw) > _MAX_SETTINGS_BYTES:
            raise ValueError("settings file exceeds size limit")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) - {
            "schema_version",
            "settings",
            "last_operation",
        }:
            raise ValueError("settings envelope contains unknown fields")
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported settings schema_version")
        settings_payload = payload.get("settings")
        if not isinstance(settings_payload, dict) or set(settings_payload) != _SETTINGS_FIELDS:
            raise ValueError("settings field set mismatch")
        settings = _view_from_payload(cast(dict[str, object], settings_payload))
        marker_payload = payload.get("last_operation")
        marker = None
        if marker_payload is not None:
            if not isinstance(marker_payload, dict) or set(marker_payload) != {
                "operation_ref",
                "patch_hash",
            }:
                raise ValueError("settings operation marker is invalid")
            marker = {key: str(value) for key, value in marker_payload.items()}
        return settings, marker

    def save(self, settings: SettingsViewV1, marker: dict[str, str] | None) -> None:
        _validate_settings(settings)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.tmp")
        payload = json.dumps(
            {
                "schema_version": 1,
                "settings": asdict(settings),
                "last_operation": marker,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > _MAX_SETTINGS_BYTES:
            raise ValueError("settings payload exceeds size limit")
        with temp_path.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, self._path)


class JsonSettingsAdapter(SettingsPort):
    def __init__(self, *, store: FileSettingsStore) -> None:
        self._store = store
        self._lock = RLock()

    def get_settings(self) -> SettingsViewV1:
        with self._lock:
            settings, _marker = self._store.load()
            return settings

    def update_settings(
        self,
        settings_patch: SettingsPatchV1,
        operation_ref: str,
    ) -> SettingsViewV1:
        if settings_patch.schema_version != 1 or not operation_ref.strip():
            raise ValueError("valid settings patch and operation_ref are required")
        with self._lock:
            current, marker = self._store.load()
            patch_hash = _patch_hash(settings_patch)
            if marker is not None and marker["operation_ref"] == operation_ref:
                if marker["patch_hash"] != patch_hash:
                    raise ValueError("operation_ref already applied to a different settings patch")
                return current
            changes = {
                name: value
                for name in _PATCH_FIELDS
                if (value := getattr(settings_patch, name)) is not None
            }
            updated = replace(current, **changes)
            _validate_settings(updated)
            self._store.save(
                updated,
                marker={"operation_ref": operation_ref, "patch_hash": patch_hash},
            )
            return updated

    def reconcile_settings(
        self,
        operation_ref: str,
        settings_patch: SettingsPatchV1,
    ) -> OperationalReconcileResultV1:
        with self._lock:
            settings, marker = self._store.load()
        completed = marker == {
            "operation_ref": operation_ref,
            "patch_hash": _patch_hash(settings_patch),
        }
        return OperationalReconcileResultV1(
            status="COMPLETED" if completed else "SAFE_TO_RETRY",
            result_ref=operation_ref if completed else None,
            bounded_result={"settings_hash": _settings_hash(settings)} if completed else None,
        )


def _view_from_payload(payload: dict[str, object]) -> SettingsViewV1:
    panel = cast(dict[str, object], payload["panel_preferences"])
    return SettingsViewV1(
        schema_version=cast(int, payload["schema_version"]),  # type: ignore[arg-type]
        timezone=str(payload["timezone"]),
        default_tasklist_id=_optional_string(payload["default_tasklist_id"]),
        default_calendar_id=_optional_string(payload["default_calendar_id"]),
        preferred_llm_mode=cast(str, payload["preferred_llm_mode"]),  # type: ignore[arg-type]
        external_llm_consent=cast(bool, payload["external_llm_consent"]),
        retention_days=int(cast(int, payload["retention_days"])),
        theme=cast(str, payload["theme"]),  # type: ignore[arg-type]
        panel_preferences=PanelPreferencesV1(
            schema_version=cast(int, panel["schema_version"]),  # type: ignore[arg-type]
            right_panel_default_open=cast(bool, panel["right_panel_default_open"]),
            right_panel_default_tab=cast(str, panel["right_panel_default_tab"]),  # type: ignore[arg-type]
        ),
        working_day_start_local=str(payload["working_day_start_local"]),
        working_day_end_local=str(payload["working_day_end_local"]),
        include_weekends=cast(bool, payload["include_weekends"]),
        calendar_buffer_minutes=int(cast(int, payload["calendar_buffer_minutes"])),
        max_run_execution_ms=int(cast(int, payload["max_run_execution_ms"])),
        max_connector_calls_per_run=int(cast(int, payload["max_connector_calls_per_run"])),
        max_source_page_calls_per_run=int(cast(int, payload["max_source_page_calls_per_run"])),
        max_detail_fetches_per_run=int(cast(int, payload["max_detail_fetches_per_run"])),
        max_context_tokens_per_run=int(cast(int, payload["max_context_tokens_per_run"])),
        max_retry_attempts_per_run=int(cast(int, payload["max_retry_attempts_per_run"])),
        circuit_failure_threshold=int(cast(int, payload["circuit_failure_threshold"])),
        circuit_open_duration_ms=int(cast(int, payload["circuit_open_duration_ms"])),
    )


def _validate_settings(settings: SettingsViewV1) -> None:
    if settings.schema_version != 1 or settings.panel_preferences.schema_version != 1:
        raise ValueError("unsupported settings schema_version")
    try:
        ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid timezone") from error
    _validate_hhmm(settings.working_day_start_local)
    _validate_hhmm(settings.working_day_end_local)
    if settings.working_day_start_local >= settings.working_day_end_local:
        raise ValueError("working day start must precede end")
    if not 1 <= settings.retention_days <= 30:
        raise ValueError("retention_days must be in 1..30")
    if settings.calendar_buffer_minutes < 0:
        raise ValueError("calendar_buffer_minutes must be non-negative")
    positive = (
        settings.max_run_execution_ms,
        settings.max_connector_calls_per_run,
        settings.max_source_page_calls_per_run,
        settings.max_detail_fetches_per_run,
        settings.max_context_tokens_per_run,
        settings.circuit_failure_threshold,
        settings.circuit_open_duration_ms,
    )
    if any(value <= 0 for value in positive) or settings.max_retry_attempts_per_run < 0:
        raise ValueError("runtime budgets and circuit settings are invalid")


def _validate_hhmm(value: str) -> None:
    if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit():
        raise ValueError("time values must use HH:MM")
    if int(value[:2]) not in range(24) or int(value[3:]) not in range(60):
        raise ValueError("time values must be valid clock times")


def _patch_hash(settings_patch: SettingsPatchV1) -> str:
    return hashlib.sha256(
        json.dumps(asdict(settings_patch), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _settings_hash(settings: SettingsViewV1) -> str:
    return hashlib.sha256(
        json.dumps(asdict(settings), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["FileSettingsStore", "JsonSettingsAdapter"]
