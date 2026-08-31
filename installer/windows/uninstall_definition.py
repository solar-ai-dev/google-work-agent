"""Canonical uninstall and user-data preservation definition."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class WindowsUninstallDefinition:
    """Separate program removal, credential deletion, and optional data purge."""

    remove_program_files: bool = True
    remove_start_menu_shortcut: bool = True
    invalidate_runtime_session: bool = True
    delete_google_oauth_keyring_entry: bool = True
    delete_llm_api_key_keyring_entry: bool = True
    preserve_database_by_default: bool = True
    preserve_backups_by_default: bool = True
    preserve_settings_by_default: bool = True
    complete_delete_requires_explicit_confirmation: bool = True
    complete_delete_paths: tuple[str, ...] = (
        "data",
        "backups",
        "settings",
        "logs",
        "diagnostics",
        "runtime",
        "staging",
    )

    def __post_init__(self) -> None:
        if not (
            self.delete_google_oauth_keyring_entry
            and self.delete_llm_api_key_keyring_entry
            and self.preserve_database_by_default
            and self.preserve_backups_by_default
            and self.preserve_settings_by_default
        ):
            raise ValueError("uninstall credential deletion and default preservation are fixed")
        if not self.complete_delete_requires_explicit_confirmation:
            raise ValueError("complete deletion must require explicit confirmation")

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema_version"] = 1
        return payload

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))


__all__ = ["WindowsUninstallDefinition"]
