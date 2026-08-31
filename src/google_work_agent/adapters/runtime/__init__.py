"""Runtime infrastructure adapters for local execution."""

from google_work_agent.adapters.runtime.safe_mode import (
    RuntimeOperation,
    SafeModeController,
    SafeModeState,
)
from google_work_agent.adapters.system.filesystem_backup import (
    BackupCreateResult,
    BackupManifestRecord,
)
from google_work_agent.adapters.system.json_settings import FileSettingsStore
from google_work_agent.adapters.system.process_shutdown import (
    ComponentShutdownPort,
    ShutdownPhase,
)
from google_work_agent.ports.system.contracts.runtime import (
    AppSettings,
    SettingsPatch,
    ShutdownReport,
    WorkHours,
)

__all__ = [
    "AppSettings",
    "BackupCreateResult",
    "BackupManifestRecord",
    "ComponentShutdownPort",
    "FileSettingsStore",
    "RuntimeOperation",
    "SafeModeController",
    "SafeModeState",
    "SettingsPatch",
    "ShutdownPhase",
    "ShutdownReport",
    "WorkHours",
]
