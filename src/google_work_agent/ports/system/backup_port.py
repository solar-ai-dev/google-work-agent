"""Local backup and restore boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass(frozen=True, slots=True)
class BackupMetadataV1:
    schema_version: Literal[1]
    backup_ref: str
    created_at_ms: int
    size_bytes: int
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class RestoreResultV1:
    schema_version: Literal[1]
    backup_ref: str
    status: Literal["RESTORED", "REJECTED"]
    detail_code: str | None


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    has_active_write: bool
    migration_running: bool
    restore_running: bool


class MaintenanceGate(Protocol):
    """Dependency-only backup/restore admission snapshot."""

    def snapshot(self) -> MaintenanceWindow: ...


class BackupPort(Protocol):
    def create_backup(self, operation_ref: str) -> BackupMetadataV1: ...

    def reconcile_backup(self, operation_ref: str) -> OperationalReconcileResultV1: ...

    def restore_backup(self, backup_ref: str, operation_ref: str) -> RestoreResultV1: ...

    def reconcile_restore(
        self, backup_ref: str, operation_ref: str
    ) -> OperationalReconcileResultV1: ...

    def list_backups(self) -> list[BackupMetadataV1]: ...


__all__ = [
    "BackupMetadataV1",
    "BackupPort",
    "MaintenanceGate",
    "MaintenanceWindow",
    "RestoreResultV1",
]
