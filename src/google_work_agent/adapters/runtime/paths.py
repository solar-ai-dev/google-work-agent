"""Production program and user-data directory contracts."""

from __future__ import annotations

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
