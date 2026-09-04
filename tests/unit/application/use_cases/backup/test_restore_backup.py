from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.application.use_cases.backup.restore_backup import (
    AutomaticallyRestoreBackupCommand,
    AutomaticallyRestoreBackupHandler,
    RestoreBackupHandler,
)
from google_work_agent.ports.system.backup_port import (
    BackupMetadataV1,
    RestoreResultV1,
)
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass
class _Backups:
    items: list[BackupMetadataV1]
    restore_calls: list[str] = field(default_factory=list)
    list_calls: int = 0

    def create_backup(self, operation_ref: str) -> BackupMetadataV1:
        raise AssertionError(f"unexpected backup creation: {operation_ref}")

    def reconcile_backup(self, operation_ref: str) -> OperationalReconcileResultV1:
        raise AssertionError(f"unexpected backup reconciliation: {operation_ref}")

    def restore_backup(self, backup_ref: str, operation_ref: str) -> RestoreResultV1:
        self.restore_calls.append(backup_ref)
        return RestoreResultV1(1, backup_ref, "RESTORED", None)

    def reconcile_restore(
        self, backup_ref: str, operation_ref: str
    ) -> OperationalReconcileResultV1:
        return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)

    def list_backups(self) -> list[BackupMetadataV1]:
        self.list_calls += 1
        return list(self.items)


def test_restore_backup__has_exact__application_owner() -> None:
    assert (
        RestoreBackupHandler.__module__
        == "google_work_agent.application.use_cases.backup.restore_backup"
    )
    assert RestoreBackupHandler.__name__ == "RestoreBackupHandler"


def test_automatic_restore__with_multiple_verified_backups__selects_latest_deterministically(
    tmp_path: Path,
) -> None:
    backups = _Backups(
        [
            BackupMetadataV1(1, "older", 1_000, 1, "hash-1"),
            BackupMetadataV1(1, "newer-b", 2_000, 1, "hash-2"),
            BackupMetadataV1(1, "newer-a", 2_000, 1, "hash-3"),
        ]
    )
    restore = RestoreBackupHandler(
        backups=backups,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
    )
    handler = AutomaticallyRestoreBackupHandler(backups=backups, restore=restore)

    result = handler(AutomaticallyRestoreBackupCommand("MIGRATION_FAILED"))

    assert result.status == "RESTORED"
    assert result.backup_ref == "newer-a"
    assert backups.restore_calls == ["newer-a"]


def test_automatic_restore__for_unrelated_failure__does_not_guess(tmp_path: Path) -> None:
    backups = _Backups([BackupMetadataV1(1, "backup", 1_000, 1, "hash")])
    restore = RestoreBackupHandler(
        backups=backups,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
    )
    handler = AutomaticallyRestoreBackupHandler(backups=backups, restore=restore)

    result = handler(AutomaticallyRestoreBackupCommand("MCP_HANDSHAKE_FAILED"))

    assert result.status == "NOT_APPLICABLE"
    assert backups.list_calls == 0
    assert backups.restore_calls == []
