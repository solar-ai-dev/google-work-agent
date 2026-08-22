"""Update user settings through the canonical Application command boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from google_work_agent.ports import SettingsPatch, WorkHours


@dataclass(frozen=True, slots=True)
class UpdateWorkHours:
    days: tuple[int, ...]
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class UpdateSettingsCommand:
    command_id: str
    requested_runtime_mode: str | None
    default_calendar_id: str | None
    default_tasklist_id: str | None
    timezone: str | None
    work_hours: UpdateWorkHours | None
    approval_ttl_minutes: int | None
    run_retention_days: int | None
    external_llm_consent: bool | None
    ollama_endpoint: str | None
    approved_model_id: str | None
    log_level: str | None


@dataclass(frozen=True, slots=True)
class UpdateSettingsResult:
    settings: dict[str, object]


class UpdateSettingsHandler:
    """Own SettingsPatch materialization and mutation dispatch."""

    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: UpdateSettingsCommand) -> UpdateSettingsResult:
        service = self._service_factory()
        if service is None:
            raise RuntimeError("SETTINGS_UNAVAILABLE")
        result = service(
            SettingsPatch(
                command_id=command.command_id,
                requested_runtime_mode=command.requested_runtime_mode,
                default_calendar_id=command.default_calendar_id,
                default_tasklist_id=command.default_tasklist_id,
                timezone=command.timezone,
                work_hours=(
                    None
                    if command.work_hours is None
                    else WorkHours(
                        days=command.work_hours.days,
                        start=command.work_hours.start,
                        end=command.work_hours.end,
                    )
                ),
                approval_ttl_minutes=command.approval_ttl_minutes,
                run_retention_days=command.run_retention_days,
                external_llm_consent=command.external_llm_consent,
                ollama_endpoint=command.ollama_endpoint,
                approved_model_id=command.approved_model_id,
                log_level=command.log_level,
            )
        )
        return UpdateSettingsResult(settings=asdict(result))
