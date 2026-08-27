"""Application services for product settings and maintenance APIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from google_work_agent.ports import (
    BackupCreateResult,
    BackupManifestRecord,
    RestorePlan,
    SettingsPatch,
    ShutdownReport,
)
from google_work_agent.ports.system.settings_port import (
    SettingsPatchV1,
    SettingsPort,
    SettingsViewV1,
)


class BackupManager(Protocol):
    def create_backup(self) -> BackupCreateResult: ...

    def list_backups(self) -> tuple[BackupManifestRecord, ...]: ...


class RestorePlanFactory(Protocol):
    def create_plan(self, backup_id: str) -> RestorePlan: ...


class ShutdownCoordinator(Protocol):
    def shutdown(self, *, timeout_seconds: float) -> ShutdownReport: ...


@dataclass(frozen=True, slots=True)
class GetSettingsService:
    service: SettingsPort

    def __call__(self) -> SettingsViewV1:
        return self.service.get_settings()


@dataclass(frozen=True, slots=True)
class PatchSettingsService:
    service: SettingsPort

    def __call__(self, patch: SettingsPatch) -> SettingsViewV1:
        unsupported = {
            "setup_completed": patch.setup_completed,
            "approval_ttl_minutes": patch.approval_ttl_minutes,
            "ollama_endpoint": patch.ollama_endpoint,
            "approved_model_id": patch.approved_model_id,
            "log_level": patch.log_level,
        }
        if any(value is not None for value in unsupported.values()):
            raise ValueError("settings patch contains fields outside canonical SettingsPatchV1")
        work_hours = patch.work_hours
        return self.service.update_settings(
            SettingsPatchV1(
                schema_version=1,
                timezone=patch.timezone,
                default_tasklist_id=patch.default_tasklist_id,
                default_calendar_id=patch.default_calendar_id,
                preferred_llm_mode=patch.requested_runtime_mode,  # type: ignore[arg-type]
                external_llm_consent=patch.external_llm_consent,
                retention_days=patch.run_retention_days,
                panel_preferences=None,
                working_day_start_local=None if work_hours is None else work_hours.start,
                working_day_end_local=None if work_hours is None else work_hours.end,
                include_weekends=(
                    None if work_hours is None else any(day in {5, 6} for day in work_hours.days)
                ),
            ),
            patch.command_id,
        )


@dataclass(frozen=True, slots=True)
class CreateBackupService:
    service: BackupManager

    def __call__(self) -> BackupCreateResult:
        return self.service.create_backup()


@dataclass(frozen=True, slots=True)
class ListBackupsService:
    service: BackupManager

    def __call__(self) -> tuple[dict[str, object], ...]:
        return tuple(asdict(item) for item in self.service.list_backups())


@dataclass(frozen=True, slots=True)
class CreateRestorePlanService:
    service: RestorePlanFactory

    def __call__(self, backup_id: str) -> RestorePlan:
        return self.service.create_plan(backup_id)


@dataclass(frozen=True, slots=True)
class RequestShutdownService:
    coordinator: ShutdownCoordinator

    def __call__(self) -> ShutdownReport:
        return self.coordinator.shutdown(timeout_seconds=30.0)
