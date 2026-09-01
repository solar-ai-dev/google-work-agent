"""Live process maintenance admission state."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from google_work_agent.ports.system.backup_port import MaintenanceWindow


class ProcessMaintenanceGateAdapter:
    """Serialize restore admission against live writes and migration lifecycle."""

    def __init__(self, *, has_active_write: Callable[[], bool]) -> None:
        self._has_active_write = has_active_write
        self._migration_running = False
        self._restore_running = False
        self._lock = RLock()

    def snapshot(self) -> MaintenanceWindow:
        with self._lock:
            return MaintenanceWindow(
                has_active_write=self._has_active_write(),
                migration_running=self._migration_running,
                restore_running=self._restore_running,
            )

    def set_migration_running(self, value: bool) -> None:
        with self._lock:
            self._migration_running = value

    def try_begin_restore(self) -> bool:
        with self._lock:
            if self._has_active_write() or self._migration_running or self._restore_running:
                return False
            self._restore_running = True
            return True

    def end_restore(self) -> None:
        with self._lock:
            self._restore_running = False


__all__ = ["ProcessMaintenanceGateAdapter"]
