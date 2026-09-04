"""Canonical non-secret settings projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class PanelPreferencesResponseV1(ApiModel):
    schema_version: Literal[1]
    right_panel_default_open: bool
    right_panel_default_tab: Literal["CONVERSATIONS", "RESOURCES"]


class SettingsResponse(ApiModel):
    schema_version: Literal[1]
    timezone: str
    default_tasklist_id: str | None
    default_calendar_id: str | None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    preferred_local_model_id: str | None
    external_llm_consent: bool
    retention_days: int
    theme: Literal["LIGHT", "DARK"]
    panel_preferences: PanelPreferencesResponseV1
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


__all__ = ["PanelPreferencesResponseV1", "SettingsResponse"]
