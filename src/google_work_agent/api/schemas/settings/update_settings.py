"""Update-settings wire request."""

from google_work_agent.api.schemas.common import ApiModel


class WorkHoursPayload(ApiModel):
    days: list[int]
    start: str
    end: str


class PatchSettingsRequest(ApiModel):
    command_id: str
    requested_runtime_mode: str | None = None
    default_calendar_id: str | None = None
    default_tasklist_id: str | None = None
    timezone: str | None = None
    work_hours: WorkHoursPayload | None = None
    approval_ttl_minutes: int | None = None
    run_retention_days: int | None = None
    external_llm_consent: bool | None = None
    ollama_endpoint: str | None = None
    approved_model_id: str | None = None
    log_level: str | None = None
