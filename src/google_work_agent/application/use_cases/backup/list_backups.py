"""List validated backup metadata through Application authority."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.system.backup_port import BackupMetadataV1, BackupPort


@dataclass(frozen=True, slots=True)
class ListBackupsQuery:
    """Read-only backup inventory request."""


@dataclass(frozen=True, slots=True)
class BackupListResponseV1:
    schema_version: int
    backups: tuple[BackupMetadataV1, ...]


class ListBackupsHandler:
    def __init__(self, backups: BackupPort) -> None:
        self._backups = backups

    def __call__(self, query: ListBackupsQuery) -> BackupListResponseV1:
        del query
        return BackupListResponseV1(1, tuple(self._backups.list_backups()))

    handle = __call__


ListBackupsResult = BackupListResponseV1

__all__ = ["BackupListResponseV1", "ListBackupsHandler", "ListBackupsQuery", "ListBackupsResult"]
