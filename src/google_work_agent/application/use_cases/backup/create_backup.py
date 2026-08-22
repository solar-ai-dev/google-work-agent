"""Create a local database backup through Application authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class CreateBackupCommand:
    """Explicit backup creation command."""


@dataclass(frozen=True, slots=True)
class CreateBackupResult:
    backup: dict[str, object]


class CreateBackupHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: CreateBackupCommand) -> CreateBackupResult:
        del command
        service = self._service_factory()
        if service is None:
            raise RuntimeError("BACKUP_UNAVAILABLE")
        result = service()
        return CreateBackupResult(
            backup={
                **asdict(result.backup),
                "database_path": str(result.database_path),
                "manifest_path": str(result.manifest_path),
            }
        )
