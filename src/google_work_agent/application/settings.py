"""Application services for product settings and maintenance APIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from google_work_agent.ports import (
    AppSettings,
    BackupCreateResult,
    BackupManifestRecord,
    RestorePlan,
    SettingsPatch,
    ShutdownReport,
)


class SettingsStore(Protocol):
    def get(self) -> AppSettings: ...

    def patch(self, patch: SettingsPatch) -> AppSettings: ...


class BackupManager(Protocol):
    def create_backup(self) -> BackupCreateResult: ...

    def list_backups(self) -> tuple[BackupManifestRecord, ...]: ...


class RestorePlanFactory(Protocol):
    def create_plan(self, backup_id: str) -> RestorePlan: ...


class ShutdownCoordinator(Protocol):
    def shutdown(self, *, timeout_seconds: float) -> ShutdownReport: ...


@dataclass(frozen=True, slots=True)
class GetSettingsService:
    service: SettingsStore

    def __call__(self) -> AppSettings:
        return self.service.get()


@dataclass(frozen=True, slots=True)
class PatchSettingsService:
    service: SettingsStore

    def __call__(self, patch: SettingsPatch) -> AppSettings:
        return self.service.patch(patch)


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
