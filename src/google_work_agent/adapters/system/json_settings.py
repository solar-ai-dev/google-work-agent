"""Canonical settings schema validation and atomic JSON storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, replace
from pathlib import Path
from threading import RLock
from typing import Literal, cast
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
_SETTINGS_FIELDS_WITHOUT_LOCAL_MODEL = _SETTINGS_FIELDS - {"preferred_local_model_id"}
_PATCH_FIELDS = frozenset(SettingsPatchV1.__dataclass_fields__) - {"schema_version"}
_LEGACY_FLAT_SETTINGS_FIELDS = frozenset(
    {
        "approval_ttl_minutes",
        "approved_model_id",
        "config_schema_version",
        "default_calendar_id",
        "default_tasklist_id",
        "deployment_profile",
        "external_llm_consent",
        "log_level",
        "ollama_endpoint",
        "requested_runtime_mode",
        "run_retention_days",
        "timezone",
        "work_hours",
    }
)
_LEGACY_WORK_HOURS_FIELDS = frozenset({"days", "end", "start"})


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
        max_source_page_calls_per_run=8,
        max_detail_fetches_per_run=12,
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
        if isinstance(payload, dict) and set(payload) == _LEGACY_FLAT_SETTINGS_FIELDS:
            settings = _migrate_legacy_flat_settings(cast(dict[str, object], payload))
            self.save(settings, marker=None)
            return settings, None
        if not isinstance(payload, dict) or set(payload) - {
            "schema_version",
            "settings",
            "last_operation",
        }:
            raise ValueError("settings envelope contains unknown fields")
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported settings schema_version")
        settings_payload = payload.get("settings")
        if not isinstance(settings_payload, dict):
            raise ValueError("settings field set mismatch")
        if set(settings_payload) == _SETTINGS_FIELDS_WITHOUT_LOCAL_MODEL:
            settings_payload = {**settings_payload, "preferred_local_model_id": None}
            settings = _view_from_payload(cast(dict[str, object], settings_payload))
            marker = _operation_marker(payload.get("last_operation"))
            self.save(settings, marker=marker)
            return settings, marker
        if set(settings_payload) != _SETTINGS_FIELDS:
            raise ValueError("settings field set mismatch")
        settings = _view_from_payload(cast(dict[str, object], settings_payload))
        marker = _operation_marker(payload.get("last_operation"))
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
    if payload["schema_version"] != 1:
        raise ValueError("unsupported settings schema_version")
    panel_value = payload["panel_preferences"]
    if not isinstance(panel_value, dict):
        raise ValueError("panel_preferences must be an object")
    panel = cast(dict[str, object], panel_value)
    if panel.get("schema_version") != 1:
        raise ValueError("unsupported panel preferences schema_version")
    preferred_llm_mode = _required_string(payload, "preferred_llm_mode")
    if preferred_llm_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
        raise ValueError("preferred_llm_mode is invalid")
    theme = _required_string(payload, "theme")
    if theme not in {"LIGHT", "DARK"}:
        raise ValueError("theme is invalid")
    default_tab = _required_string(panel, "right_panel_default_tab")
    if default_tab not in {"CONVERSATIONS", "RESOURCES"}:
        raise ValueError("right_panel_default_tab is invalid")
    return SettingsViewV1(
        schema_version=1,
        timezone=_required_string(payload, "timezone"),
        default_tasklist_id=_optional_string(payload["default_tasklist_id"]),
        default_calendar_id=_optional_string(payload["default_calendar_id"]),
        preferred_llm_mode=cast(Literal["AUTO", "LOCAL_GPU", "API_LLM"], preferred_llm_mode),
        external_llm_consent=_required_bool(payload, "external_llm_consent"),
        retention_days=_required_int(payload, "retention_days"),
        theme=cast(Literal["LIGHT", "DARK"], theme),
        panel_preferences=PanelPreferencesV1(
            schema_version=1,
            right_panel_default_open=_required_bool(panel, "right_panel_default_open"),
            right_panel_default_tab=cast(Literal["CONVERSATIONS", "RESOURCES"], default_tab),
        ),
        working_day_start_local=_required_string(payload, "working_day_start_local"),
        working_day_end_local=_required_string(payload, "working_day_end_local"),
        include_weekends=_required_bool(payload, "include_weekends"),
        calendar_buffer_minutes=_required_int(payload, "calendar_buffer_minutes"),
        max_run_execution_ms=_required_int(payload, "max_run_execution_ms"),
        max_connector_calls_per_run=_required_int(payload, "max_connector_calls_per_run"),
        max_source_page_calls_per_run=_required_int(payload, "max_source_page_calls_per_run"),
        max_detail_fetches_per_run=_required_int(payload, "max_detail_fetches_per_run"),
        max_context_tokens_per_run=_required_int(payload, "max_context_tokens_per_run"),
        max_retry_attempts_per_run=_required_int(payload, "max_retry_attempts_per_run"),
        circuit_failure_threshold=_required_int(payload, "circuit_failure_threshold"),
        circuit_open_duration_ms=_required_int(payload, "circuit_open_duration_ms"),
        preferred_local_model_id=_optional_string(payload["preferred_local_model_id"]),
    )


def _migrate_legacy_flat_settings(payload: dict[str, object]) -> SettingsViewV1:
    """Atomically cut over the exact retired flat settings envelope."""

    if _required_int(payload, "config_schema_version") != 1:
        raise ValueError("unsupported legacy settings schema_version")
    work_hours_value = payload["work_hours"]
    if not isinstance(work_hours_value, dict) or set(work_hours_value) != _LEGACY_WORK_HOURS_FIELDS:
        raise ValueError("legacy work_hours field set mismatch")
    work_hours = cast(dict[str, object], work_hours_value)
    days = work_hours["days"]
    if not isinstance(days, list) or any(
        not isinstance(day, int) or isinstance(day, bool) for day in days
    ):
        raise ValueError("legacy work_hours days are invalid")
    ordered_days = tuple(cast(list[int], days))
    if ordered_days == (0, 1, 2, 3, 4):
        include_weekends = False
    elif ordered_days == (0, 1, 2, 3, 4, 5, 6):
        include_weekends = True
    else:
        raise ValueError("legacy work_hours days cannot be represented")

    preferred_llm_mode = _required_string(payload, "requested_runtime_mode")
    if preferred_llm_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
        raise ValueError("legacy requested_runtime_mode is invalid")
    settings = replace(
        _default_settings(),
        timezone=_required_string(payload, "timezone"),
        default_tasklist_id=_optional_string(payload["default_tasklist_id"]),
        default_calendar_id=_optional_string(payload["default_calendar_id"]),
        preferred_llm_mode=cast(
            Literal["AUTO", "LOCAL_GPU", "API_LLM"], preferred_llm_mode
        ),
        external_llm_consent=_required_bool(payload, "external_llm_consent"),
        retention_days=_required_int(payload, "run_retention_days"),
        working_day_start_local=_required_string(work_hours, "start"),
        working_day_end_local=_required_string(work_hours, "end"),
        include_weekends=include_weekends,
    )
    _validate_settings(settings)
    return settings


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


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
    if settings.preferred_local_model_id is not None and (
        not settings.preferred_local_model_id.strip()
        or len(settings.preferred_local_model_id) > 200
        or re.search(r"[\x00-\x1f\x7f]", settings.preferred_local_model_id)
    ):
        raise ValueError("preferred_local_model_id is invalid")
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


def _operation_marker(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"operation_ref", "patch_hash"}:
        raise ValueError("settings operation marker is invalid")
    return {key: str(item) for key, item in value.items()}


__all__ = ["FileSettingsStore", "JsonSettingsAdapter"]
