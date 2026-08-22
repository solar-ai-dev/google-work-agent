"""List validated backup metadata through Application authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ListBackupsQuery:
    """Read-only backup inventory request."""


@dataclass(frozen=True, slots=True)
class ListBackupsResult:
    items: tuple[object, ...]


class ListBackupsHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, query: ListBackupsQuery) -> ListBackupsResult:
        del query
        service = self._service_factory()
        if service is None:
            raise RuntimeError("BACKUP_UNAVAILABLE")
        return ListBackupsResult(items=tuple(service()))
