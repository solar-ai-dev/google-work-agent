"""Versioned non-secret settings storage boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass(frozen=True, slots=True)
class PanelPreferencesV1:
    schema_version: Literal[1]
    right_panel_default_open: bool
    right_panel_default_tab: Literal["CONVERSATIONS", "RESOURCES"]


@dataclass(frozen=True, slots=True)
class SettingsPatchV1:
    schema_version: Literal[1]
    timezone: str | None = None
    default_tasklist_id: str | None = None
    default_calendar_id: str | None = None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"] | None = None
    external_llm_consent: bool | None = None
    retention_days: int | None = None
    theme: Literal["LIGHT", "DARK"] | None = None
    panel_preferences: PanelPreferencesV1 | None = None
    working_day_start_local: str | None = None
    working_day_end_local: str | None = None
    include_weekends: bool | None = None
    calendar_buffer_minutes: int | None = None
    max_run_execution_ms: int | None = None
    max_connector_calls_per_run: int | None = None
    max_source_page_calls_per_run: int | None = None
    max_detail_fetches_per_run: int | None = None
    max_context_tokens_per_run: int | None = None
    max_retry_attempts_per_run: int | None = None
    circuit_failure_threshold: int | None = None
    circuit_open_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SettingsViewV1:
    schema_version: Literal[1]
    timezone: str
    default_tasklist_id: str | None
    default_calendar_id: str | None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    external_llm_consent: bool
    retention_days: int
    theme: Literal["LIGHT", "DARK"]
    panel_preferences: PanelPreferencesV1
    working_day_start_local: str
    working_day_end_local: str
    include_weekends: bool
    calendar_buffer_minutes: int
    max_run_execution_ms: int
    max_connector_calls_per_run: int
    max_source_page_calls_per_run: int
    max_detail_fetches_per_run: int
    max_context_tokens_per_run: int
    max_retry_attempts_per_run: int
    circuit_failure_threshold: int
    circuit_open_duration_ms: int


class SettingsPort(Protocol):
    def get_settings(self) -> SettingsViewV1: ...

    def update_settings(
        self, settings_patch: SettingsPatchV1, operation_ref: str
    ) -> SettingsViewV1: ...

    def reconcile_settings(
        self, operation_ref: str, settings_patch: SettingsPatchV1
    ) -> OperationalReconcileResultV1: ...


__all__ = ["PanelPreferencesV1", "SettingsPatchV1", "SettingsPort", "SettingsViewV1"]
