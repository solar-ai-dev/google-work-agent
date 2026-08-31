"""Runtime infrastructure adapters for packaging and local execution."""

from google_work_agent.adapters.runtime.build_manifest import (
    ArtifactRecord,
    BuildArtifactType,
    BuildManifestVerifier,
    BuildProfile,
    FrontendSite,
    SignedBuildManifest,
    SigningStatus,
)
from google_work_agent.adapters.runtime.paths import ProductProgramLayout
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
    "ArtifactRecord",
    "BackupCreateResult",
    "BackupManifestRecord",
    "BuildArtifactType",
    "BuildManifestVerifier",
    "BuildProfile",
    "ComponentShutdownPort",
    "FileSettingsStore",
    "FrontendSite",
    "ProductProgramLayout",
    "RuntimeOperation",
    "SafeModeController",
    "SafeModeState",
    "SettingsPatch",
    "ShutdownPhase",
    "ShutdownReport",
    "SignedBuildManifest",
    "SigningStatus",
    "WorkHours",
]
