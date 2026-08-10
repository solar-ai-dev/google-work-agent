"""Settings schema validation and atomic file storage."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.adapters.runtime.build_manifest import BuildProfile

_MAX_SETTINGS_BYTES = 32 * 1024
_SECRET_LIKE_KEYS = {
    "refresh_token",
    "access_token",
    "api_key",
    "password",
    "bootstrap",
    "session",
    "client_secret",
    "claim_token",
}


@dataclass(frozen=True, slots=True)
class WorkHours:
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    start: str = "09:00"
    end: str = "18:00"


@dataclass(frozen=True, slots=True)
class AppSettings:
    config_schema_version: int = 1
    deployment_profile: str = BuildProfile.API_ONLY.value
    requested_runtime_mode: str = "API_LLM"
    default_calendar_id: str | None = None
    default_tasklist_id: str | None = None
    timezone: str = "Asia/Seoul"
    work_hours: WorkHours = WorkHours()
    approval_ttl_minutes: int = 30
    run_retention_days: int = 30
    external_llm_consent: bool = False
    ollama_endpoint: str | None = None
    approved_model_id: str | None = None
    log_level: str = "INFO"


@dataclass(frozen=True, slots=True)
class SettingsPatch:
    command_id: str
    requested_runtime_mode: str | None = None
    default_calendar_id: str | None = None
    default_tasklist_id: str | None = None
    timezone: str | None = None
    work_hours: WorkHours | None = None
    approval_ttl_minutes: int | None = None
    run_retention_days: int | None = None
    external_llm_consent: bool | None = None
    ollama_endpoint: str | None = None
    approved_model_id: str | None = None
    log_level: str | None = None


class FileSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(
        self,
        *,
        deployment_profile: BuildProfile,
        approved_model_ids: frozenset[str] | None = None,
    ) -> AppSettings:
        if not self._path.exists():
            settings = AppSettings(deployment_profile=deployment_profile.value)
            self.save(settings)
            return settings
        raw = self._path.read_bytes()
        if len(raw) > _MAX_SETTINGS_BYTES:
            raise ValueError("settings file exceeds size limit")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("settings payload must be an object")
        _reject_secret_keys(payload)
        _reject_unknown_fields(payload)
        settings = _settings_from_dict(payload)
        validate_settings(
            settings=settings,
            deployment_profile=deployment_profile,
            approved_model_ids=approved_model_ids,
        )
        return settings

    def save(self, settings: AppSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        payload = json.dumps(asdict(settings), ensure_ascii=False, sort_keys=True, indent=2)
        data = payload.encode("utf-8")
        if len(data) > _MAX_SETTINGS_BYTES:
            raise ValueError("settings payload exceeds size limit")
        with temp_path.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, self._path)


class SettingsService:
    def __init__(
        self,
        *,
        store: FileSettingsStore,
        deployment_profile: BuildProfile,
        approved_model_ids: frozenset[str],
        has_active_runs: Callable[[], bool],
    ) -> None:
        self._store = store
        self._deployment_profile = deployment_profile
        self._approved_model_ids = approved_model_ids
        self._has_active_runs = has_active_runs

    def get(self) -> AppSettings:
        return self._store.load(
            deployment_profile=self._deployment_profile,
            approved_model_ids=self._approved_model_ids,
        )

    def patch(self, patch: SettingsPatch) -> AppSettings:
        current = self.get()
        if patch.requested_runtime_mode is not None and self._has_active_runs():
            raise ValueError("requested_runtime_mode cannot change while a run is active")
        updated = replace(
            current,
            requested_runtime_mode=patch.requested_runtime_mode
            if patch.requested_runtime_mode is not None
            else current.requested_runtime_mode,
            default_calendar_id=patch.default_calendar_id
            if patch.default_calendar_id is not None
            else current.default_calendar_id,
            default_tasklist_id=patch.default_tasklist_id
            if patch.default_tasklist_id is not None
            else current.default_tasklist_id,
            timezone=patch.timezone if patch.timezone is not None else current.timezone,
            work_hours=patch.work_hours if patch.work_hours is not None else current.work_hours,
            approval_ttl_minutes=patch.approval_ttl_minutes
            if patch.approval_ttl_minutes is not None
            else current.approval_ttl_minutes,
            run_retention_days=patch.run_retention_days
            if patch.run_retention_days is not None
            else current.run_retention_days,
            external_llm_consent=patch.external_llm_consent
            if patch.external_llm_consent is not None
            else current.external_llm_consent,
            ollama_endpoint=patch.ollama_endpoint
            if patch.ollama_endpoint is not None
            else current.ollama_endpoint,
            approved_model_id=patch.approved_model_id
            if patch.approved_model_id is not None
            else current.approved_model_id,
            log_level=patch.log_level if patch.log_level is not None else current.log_level,
        )
        validate_settings(
            settings=updated,
            deployment_profile=self._deployment_profile,
            approved_model_ids=self._approved_model_ids,
        )
        self._store.save(updated)
        return updated


def validate_settings(
    *,
    settings: AppSettings,
    deployment_profile: BuildProfile,
    approved_model_ids: frozenset[str] | None = None,
) -> None:
    if settings.deployment_profile != deployment_profile.value:
        raise ValueError("deployment_profile is build-fixed")
    if settings.requested_runtime_mode not in {"API_LLM", "AUTO", "LOCAL_GPU"}:
        raise ValueError("invalid requested_runtime_mode")
    if deployment_profile is BuildProfile.API_ONLY and settings.requested_runtime_mode != "API_LLM":
        raise ValueError("API_ONLY build cannot enable local runtime modes")
    try:
        ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid timezone") from error
    _validate_work_hours(settings.work_hours)
    if not 5 <= settings.approval_ttl_minutes <= 120:
        raise ValueError("approval_ttl_minutes out of range")
    if not 1 <= settings.run_retention_days <= 365:
        raise ValueError("run_retention_days out of range")
    if settings.log_level not in {"INFO", "WARNING", "ERROR", "DEBUG"}:
        raise ValueError("invalid log_level")
    if deployment_profile is BuildProfile.LOCAL_CAPABLE:
        if settings.ollama_endpoint is not None:
            _validate_loopback_url(settings.ollama_endpoint)
    elif settings.ollama_endpoint is not None:
        raise ValueError("ollama_endpoint is only allowed for LOCAL_CAPABLE")
    if settings.approved_model_id is not None and (
        not approved_model_ids or settings.approved_model_id not in approved_model_ids
    ):
        raise ValueError("approved_model_id is not allowed")


def _validate_work_hours(value: WorkHours) -> None:
    if not value.days:
        raise ValueError("work_hours.days must not be empty")
    if any(day < 0 or day > 6 for day in value.days):
        raise ValueError("work_hours.days must be 0..6")
    for field in (value.start, value.end):
        _validate_hhmm(field)


def _validate_hhmm(value: str) -> None:
    if len(value) != 5 or value[2] != ":":
        raise ValueError("time values must use HH:MM")
    hour, minute = value.split(":")
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError("time values must use HH:MM")
    parsed_hour = int(hour)
    parsed_minute = int(minute)
    if parsed_hour not in range(24) or parsed_minute not in range(60):
        raise ValueError("time values must be valid clock times")


def _validate_loopback_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "http":
        raise ValueError("ollama_endpoint must use http")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("ollama_endpoint must stay on loopback")
    if parsed.port is None:
        raise ValueError("ollama_endpoint must include an explicit port")


def _reject_secret_keys(payload: dict[str, object]) -> None:
    for key in payload:
        if key.lower() in _SECRET_LIKE_KEYS:
            raise ValueError(f"secret-like settings key is forbidden: {key}")


def _reject_unknown_fields(payload: dict[str, object]) -> None:
    allowed = set(AppSettings.__dataclass_fields__.keys())
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown settings fields: {sorted(unknown)}")


def _settings_from_dict(payload: dict[str, object]) -> AppSettings:
    work_hours_payload = payload.get("work_hours", {})
    if not isinstance(work_hours_payload, dict):
        raise ValueError("work_hours must be an object")
    work_hours = WorkHours(
        days=tuple(_as_int(day) for day in work_hours_payload.get("days", (0, 1, 2, 3, 4))),
        start=str(work_hours_payload.get("start", "09:00")),
        end=str(work_hours_payload.get("end", "18:00")),
    )
    return AppSettings(
        config_schema_version=_as_int(payload.get("config_schema_version", 1)),
        deployment_profile=str(payload.get("deployment_profile", BuildProfile.API_ONLY.value)),
        requested_runtime_mode=str(payload.get("requested_runtime_mode", "API_LLM")),
        default_calendar_id=_optional_text(payload.get("default_calendar_id")),
        default_tasklist_id=_optional_text(payload.get("default_tasklist_id")),
        timezone=str(payload.get("timezone", "Asia/Seoul")),
        work_hours=work_hours,
        approval_ttl_minutes=_as_int(payload.get("approval_ttl_minutes", 30)),
        run_retention_days=_as_int(payload.get("run_retention_days", 30)),
        external_llm_consent=bool(payload.get("external_llm_consent", False)),
        ollama_endpoint=_optional_text(payload.get("ollama_endpoint")),
        approved_model_id=_optional_text(payload.get("approved_model_id")),
        log_level=str(payload.get("log_level", "INFO")),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_int(value: object) -> int:
    return int(str(value))
