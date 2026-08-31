"""Create the current-user product data layout and initialize its ACL."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class DataDirectoryPreparationError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class DataDirectoryLayout:
    root: Path
    data_dir: Path
    backups_dir: Path
    settings_dir: Path
    logs_dir: Path
    diagnostics_dir: Path
    runtime_dir: Path
    cache_dir: Path
    attachment_cache_dir: Path

    @property
    def service_instance_path(self) -> Path:
        return self.runtime_dir / "service-instance.json"

    @property
    def service_lock_path(self) -> Path:
        return self.runtime_dir / "service.lock"

    @property
    def shutdown_marker_path(self) -> Path:
        return self.runtime_dir / "shutdown.marker"


def prepare_data_directory(
    data_root: Path | None = None,
    *,
    acl_initializer: Callable[[Path], None] | None = None,
) -> DataDirectoryLayout:
    """Create the canonical layout and restrict it to current user plus SYSTEM."""

    root = (data_root or _default_data_root()).resolve()
    layout = DataDirectoryLayout(
        root=root,
        data_dir=root / "data",
        backups_dir=root / "backups",
        settings_dir=root / "settings",
        logs_dir=root / "logs",
        diagnostics_dir=root / "diagnostics",
        runtime_dir=root / "runtime",
        cache_dir=root / "cache",
        attachment_cache_dir=root / "cache" / "attachments",
    )
    try:
        for path in (
            layout.root,
            layout.data_dir,
            layout.backups_dir,
            layout.settings_dir,
            layout.logs_dir,
            layout.diagnostics_dir,
            layout.runtime_dir,
            layout.cache_dir,
            layout.attachment_cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        (acl_initializer or _apply_current_user_acl)(layout.root)
    except (OSError, subprocess.SubprocessError) as error:
        raise DataDirectoryPreparationError("DATA_DIR_UNAVAILABLE") from error
    return layout


def _default_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise DataDirectoryPreparationError("LOCALAPPDATA_UNAVAILABLE")
    return Path(local_app_data) / "GoogleWorkAgent"


def _apply_current_user_acl(path: Path) -> None:
    if os.name != "nt":
        raise DataDirectoryPreparationError("UNSUPPORTED_OS")
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    match = re.search(r"S-1-[0-9-]+", identity)
    if match is None:
        raise DataDirectoryPreparationError("FILE_PERMISSION_DENIED")
    current_user_sid = match.group(0)
    subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{current_user_sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "/T",
            "/C",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
