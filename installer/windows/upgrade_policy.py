"""Canonical signed in-place upgrade and downgrade-block policy."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)*")


@dataclass(frozen=True, slots=True)
class UpgradeAssessment:
    allowed: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class WindowsUpgradePolicy:
    """Validate preconditions before an atomic signed program-file replacement."""

    manual_in_place_only: bool = True
    require_signed_installer: bool = True
    require_running_instance_shutdown: bool = True
    require_active_write_safe_state: bool = True
    require_pre_migration_backup: bool = True
    require_migration_readiness: bool = True
    atomic_program_replacement: bool = True
    rollback_program_files_on_failure: bool = True
    preserve_database: bool = True
    preserve_backups: bool = True
    preserve_settings: bool = True
    preserve_keyring_entries_during_upgrade: bool = True
    block_downgrade: bool = True

    def assess(
        self,
        *,
        current_app_version: str,
        candidate_app_version: str,
        installer_signature_verified: bool,
        application_stopped: bool,
        active_write_safe: bool,
        pre_migration_backup_created: bool,
        migration_ready: bool,
        development_downgrade_override: bool = False,
    ) -> UpgradeAssessment:
        current = _version_tuple(current_app_version)
        candidate = _version_tuple(candidate_app_version)
        if not installer_signature_verified:
            return UpgradeAssessment(False, "INSTALLER_SIGNATURE_INVALID")
        if not application_stopped:
            return UpgradeAssessment(False, "RUNNING_INSTANCE_PRESENT")
        if not active_write_safe:
            return UpgradeAssessment(False, "ACTIVE_WRITE_UNSAFE")
        if not pre_migration_backup_created:
            return UpgradeAssessment(False, "PRE_MIGRATION_BACKUP_REQUIRED")
        if not migration_ready:
            return UpgradeAssessment(False, "MIGRATION_NOT_READY")
        if candidate < current and not development_downgrade_override:
            return UpgradeAssessment(False, "DOWNGRADE_BLOCKED")
        if candidate == current:
            return UpgradeAssessment(False, "VERSION_NOT_ADVANCED")
        return UpgradeAssessment(True, "UPGRADE_ALLOWED")

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema_version"] = 1
        return payload

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))


def _version_tuple(value: str) -> tuple[int, ...]:
    if _VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("app version must be a dot-separated numeric version")
    return tuple(int(part) for part in value.split("."))


__all__ = ["UpgradeAssessment", "WindowsUpgradePolicy"]
