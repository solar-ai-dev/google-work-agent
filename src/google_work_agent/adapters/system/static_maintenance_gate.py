"""Static maintenance-window adapter for environments without a dynamic probe."""

from dataclasses import dataclass

from google_work_agent.ports.system.backup_port import MaintenanceGate, MaintenanceWindow


@dataclass(frozen=True, slots=True)
class StaticMaintenanceGateAdapter(MaintenanceGate):
    has_active_write: bool = False
    migration_running: bool = False
    restore_running: bool = False

    def snapshot(self) -> MaintenanceWindow:
        return MaintenanceWindow(
            has_active_write=self.has_active_write,
            migration_running=self.migration_running,
            restore_running=self.restore_running,
        )


__all__ = ["StaticMaintenanceGateAdapter"]
