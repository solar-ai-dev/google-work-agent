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
from google_work_agent.adapters.runtime.crash import CrashMarker, CrashMarkerStore
from google_work_agent.adapters.runtime.launcher import (
    BrowserLauncher,
    BrowserLaunchRequest,
    DynamicLoopbackPortAllocator,
    InstanceAcquireResult,
    InstanceRegistry,
    LauncherCore,
    LauncherPort,
    LauncherState,
    LauncherStatus,
    ServiceLaunchRequest,
    ServiceProcessHandle,
    ServiceProcessLauncher,
)
from google_work_agent.adapters.runtime.paths import ProductDataLayout, ProductProgramLayout
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
from google_work_agent.ports import (
    AppSettings,
    SettingsPatch,
    WorkHours,
)
from google_work_agent.ports.runtime_contracts import ShutdownReport

__all__ = [
    "AppSettings",
    "ArtifactRecord",
    "BackupCreateResult",
    "BackupManifestRecord",
    "BrowserLaunchRequest",
    "BrowserLauncher",
    "BuildArtifactType",
    "BuildManifestVerifier",
    "BuildProfile",
    "ComponentShutdownPort",
    "CrashMarker",
    "CrashMarkerStore",
    "DynamicLoopbackPortAllocator",
    "FileSettingsStore",
    "FrontendSite",
    "InstanceAcquireResult",
    "InstanceRegistry",
    "LauncherCore",
    "LauncherPort",
    "LauncherState",
    "LauncherStatus",
    "ProductDataLayout",
    "ProductProgramLayout",
    "RuntimeOperation",
    "SafeModeController",
    "SafeModeState",
    "ServiceLaunchRequest",
    "ServiceProcessHandle",
    "ServiceProcessLauncher",
    "SettingsPatch",
    "ShutdownPhase",
    "ShutdownReport",
    "SignedBuildManifest",
    "SigningStatus",
    "WorkHours",
]
