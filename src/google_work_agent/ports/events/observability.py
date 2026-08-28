"""Event-boundary observability port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OperationalLogRecord:
    """One sanitized operational log line."""

    event_json: str
    occurred_at_ms: int


class OperationalLogSink(Protocol):
    """Append-only operational log sink."""

    def append(self, record: OperationalLogRecord) -> None:
        """Append one sanitized operational log line."""


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    """Flags that can block purge work."""

    has_active_write: bool
    migration_running: bool
    restore_running: bool


class MaintenanceGate(Protocol):
    """Reports whether maintenance-sensitive work may proceed."""

    def snapshot(self) -> MaintenanceWindow:
        """Return the current maintenance window flags."""
