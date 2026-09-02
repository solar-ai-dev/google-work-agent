"""Persisted user application-setting contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkHours:
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    start: str = "09:00"
    end: str = "18:00"


@dataclass(frozen=True, slots=True)
class AppSettings:
    config_schema_version: int = 1
    setup_completed: bool = False
    deployment_profile: str = "API_ONLY"
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
