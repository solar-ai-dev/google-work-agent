"""Local backup boundary."""

from typing import Protocol

from google_work_agent.ports.runtime_contracts import (
    BackupCreateResult,
    BackupManifestRecord,
    RestorePlan,
)


class BackupPort(Protocol):
    def create_backup(self) -> BackupCreateResult: ...
    def list_backups(self) -> tuple[BackupManifestRecord, ...]: ...
    def create_plan(self, backup_id: str) -> RestorePlan: ...
