"""Runtime infrastructure adapters for packaging and local execution."""

from google_work_agent.adapters.system.filesystem_backup import (
    BackupCreateResult,
    BackupManifestRecord,
    BackupService,
    RestorePlan,
    RestorePlanner,
)
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
from google_work_agent.adapters.system.json_settings import (
    AppSettings,
    FileSettingsStore,
    SettingsPatch,
    SettingsService,
    WorkHours,
)
from google_work_agent.adapters.system.process_shutdown import (
    ComponentShutdownPort,
    GracefulShutdownCoordinator,
    ShutdownPhase,
    ShutdownReport,
)

__all__ = [
    "AppSettings",
    "ArtifactRecord",
    "BackupCreateResult",
    "BackupManifestRecord",
    "BackupService",
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
    "GracefulShutdownCoordinator",
    "InstanceAcquireResult",
    "InstanceRegistry",
    "LauncherCore",
    "LauncherPort",
    "LauncherState",
    "LauncherStatus",
    "ProductDataLayout",
    "ProductProgramLayout",
    "RestorePlan",
    "RestorePlanner",
    "RuntimeOperation",
    "SafeModeController",
    "SafeModeState",
    "ServiceLaunchRequest",
    "ServiceProcessHandle",
    "ServiceProcessLauncher",
    "SettingsPatch",
    "SettingsService",
    "ShutdownPhase",
    "ShutdownReport",
    "SignedBuildManifest",
    "SigningStatus",
    "WorkHours",
]
