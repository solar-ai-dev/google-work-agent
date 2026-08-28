"""Restore a validated backup through crash-safe operational replay."""

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.backup_port import BackupPort, RestoreResultV1
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class RestoreBackupCommand:
    command_id: str
    backup_ref: str


@dataclass(frozen=True, slots=True)
class RestoreBackupResult:
    restore: RestoreResultV1
    operation_ref: str
    replayed: bool


class RestoreBackupHandler:
    def __init__(self, *, backups: BackupPort, replay: OperationalCommandReplayPort) -> None:
        self._backups = backups
        self._replay = replay

    def __call__(self, command: RestoreBackupCommand) -> RestoreBackupResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._backups.restore_backup(command.backup_ref, ref)
            return command.backup_ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="RESTORE_BACKUP",
            request_payload={"backup_ref": command.backup_ref},
            reconcile=lambda ref: self._backups.reconcile_restore(command.backup_ref, ref),
            execute=execute,
        )
        return RestoreBackupResult(
            restore=RestoreResultV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["RestoreBackupCommand", "RestoreBackupHandler", "RestoreBackupResult"]
