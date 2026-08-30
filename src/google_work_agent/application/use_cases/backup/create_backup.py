"""Create a local database backup through Application authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.backup_port import BackupMetadataV1, BackupPort
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class CreateBackupCommand:
    command_id: str


@dataclass(frozen=True, slots=True)
class CreateBackupResult:
    backup: BackupMetadataV1
    operation_ref: str
    replayed: bool


class CreateBackupHandler:
    def __init__(self, *, backups: BackupPort, replay: OperationalCommandReplayPort) -> None:
        self._backups = backups
        self._replay = replay

    def __call__(self, command: CreateBackupCommand) -> CreateBackupResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._backups.create_backup(ref)
            return value.backup_ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="CREATE_BACKUP",
            request_payload={},
            reconcile=self._backups.reconcile_backup,
            execute=execute,
        )
        return CreateBackupResult(
            backup=BackupMetadataV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )

__all__ = ["CreateBackupCommand", "CreateBackupHandler", "CreateBackupResult"]
