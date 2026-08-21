"""Stable external settings and maintenance transport contracts."""

from .create_backup import BackupResponse
from .create_restore_plan import RestorePlanRequest, RestorePlanResponse
from .get_settings import SettingsResponse
from .list_backups import BackupListResponse
from .request_shutdown import ShutdownResponse
from .update_settings import PatchSettingsRequest, WorkHoursPayload

__all__ = [
    "BackupListResponse",
    "BackupResponse",
    "PatchSettingsRequest",
    "RestorePlanRequest",
    "RestorePlanResponse",
    "SettingsResponse",
    "ShutdownResponse",
    "WorkHoursPayload",
]
