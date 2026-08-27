"""Production program and user-data directory contracts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductProgramLayout:
    root: Path
    launcher_dir: Path
    service_dir: Path
    frontend_dir: Path
    mcp_dir: Path
    runtime_dir: Path
    schemas_dir: Path
    migrations_dir: Path
    manifests_dir: Path
    uninstaller_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> ProductProgramLayout:
        base = root.resolve()
        return cls(
            root=base,
            launcher_dir=base / "launcher",
            service_dir=base / "service",
            frontend_dir=base / "frontend",
            mcp_dir=base / "mcp",
            runtime_dir=base / "runtime",
            schemas_dir=base / "schemas",
            migrations_dir=base / "migrations",
            manifests_dir=base / "manifests",
            uninstaller_dir=base / "uninstaller",
        )


@dataclass(frozen=True, slots=True)
class ProductDataLayout:
    root: Path
    data_dir: Path
    backups_dir: Path
    settings_dir: Path
    logs_dir: Path
    diagnostics_dir: Path
    runtime_dir: Path
    cache_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> ProductDataLayout:
        base = root.resolve()
        return cls(
            root=base,
            data_dir=base / "data",
            backups_dir=base / "backups",
            settings_dir=base / "settings",
            logs_dir=base / "logs",
            diagnostics_dir=base / "diagnostics",
            runtime_dir=base / "runtime",
            cache_dir=base / "cache",
        )

    @classmethod
    def for_current_user(cls) -> ProductDataLayout:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is required for the production data layout")
        return cls.from_root(Path(local_app_data) / "GoogleWorkAgent")

    @property
    def settings_file(self) -> Path:
        return self.settings_dir / "app-settings.json"
