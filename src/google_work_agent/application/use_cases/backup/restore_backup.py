"""Restore a validated backup through crash-safe operational replay."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

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


_AUTOMATIC_RESTORE_FAILURES = frozenset({"MIGRATION_FAILED", "DB_INTEGRITY_FAILED"})


@dataclass(frozen=True, slots=True)
class AutomaticallyRestoreBackupCommand:
    failure_code: str


@dataclass(frozen=True, slots=True)
class AutomaticallyRestoreBackupResult:
    status: Literal["NOT_APPLICABLE", "NO_ELIGIBLE_BACKUP", "RESTORED", "REJECTED"]
    backup_ref: str | None
    detail_code: str | None


class AutomaticallyRestoreBackupHandler:
    """Select one verified candidate and delegate to the sole restore authority."""

    def __init__(self, *, backups: BackupPort, restore: RestoreBackupHandler) -> None:
        self._backups = backups
        self._restore = restore

    def __call__(
        self, command: AutomaticallyRestoreBackupCommand
    ) -> AutomaticallyRestoreBackupResult:
        if command.failure_code not in _AUTOMATIC_RESTORE_FAILURES:
            return AutomaticallyRestoreBackupResult("NOT_APPLICABLE", None, None)
        candidates = sorted(
            self._backups.list_backups(),
            key=lambda item: (-item.created_at_ms, item.backup_ref),
        )
        if not candidates:
            return AutomaticallyRestoreBackupResult("NO_ELIGIBLE_BACKUP", None, None)
        candidate = candidates[0]
        restored = self._restore(
            RestoreBackupCommand(
                command_id=(
                    f"system:auto-restore:{command.failure_code}:{candidate.backup_ref}"
                ),
                backup_ref=candidate.backup_ref,
            )
        ).restore
        return AutomaticallyRestoreBackupResult(
            "RESTORED" if restored.status == "RESTORED" else "REJECTED",
            candidate.backup_ref,
            restored.detail_code,
        )


__all__ = [
    "AutomaticallyRestoreBackupCommand",
    "AutomaticallyRestoreBackupHandler",
    "AutomaticallyRestoreBackupResult",
    "RestoreBackupCommand",
    "RestoreBackupHandler",
    "RestoreBackupResult",
]
