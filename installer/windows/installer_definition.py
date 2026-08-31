"""Declarative Windows per-user installer contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WindowsInstallerDefinition:
    """Canonical Windows x64, current-user installation definition."""

    app_id: str = "GoogleWorkAgent"
    app_name: str = "Google Work Agent"
    publisher: str = "Solar AI"
    architecture: str = "x64"
    install_scope: str = "CURRENT_USER"
    install_root: str = "%LOCALAPPDATA%/Programs/GoogleWorkAgent"
    launcher_relative_path: str = "launcher/GoogleWorkAgentLauncher.exe"
    start_menu_shortcut: bool = True
    requires_administrator: bool = False
    rollback_program_files_on_failure: bool = True
    verify_release_signature_before_install: bool = True
    require_code_signature: bool = True

    def __post_init__(self) -> None:
        if self.architecture != "x64" or self.install_scope != "CURRENT_USER":
            raise ValueError("only the canonical Windows x64 current-user install is supported")
        if self.requires_administrator:
            raise ValueError("the canonical installer must not require administrator privileges")
        if not self.launcher_relative_path.endswith("GoogleWorkAgentLauncher.exe"):
            raise ValueError("canonical Launcher entrypoint is required")

    def to_payload(self) -> dict[str, object]:
        return asdict(self)

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))

    def render_inno_setup_script(
        self,
        *,
        bundle_root: Path,
        output_dir: Path,
        app_version: str,
        deployment_profile: str,
    ) -> str:
        """Render the private Inno Setup backend input for the canonical definition."""

        if not bundle_root.is_absolute() or not output_dir.is_absolute():
            raise ValueError("installer build paths must be absolute")
        if deployment_profile not in {"API_ONLY", "LOCAL_CAPABLE"}:
            raise ValueError("unsupported deployment profile")
        if not app_version.strip():
            raise ValueError("app_version is required")
        source = _inno_quote(str(bundle_root / "*"))
        output = _inno_quote(str(output_dir))
        launcher = self.launcher_relative_path.replace("/", "\\")
        filename = f"GoogleWorkAgent-{app_version}-{deployment_profile}-Setup"
        return "\n".join(
            (
                "[Setup]",
                f"AppId={{{self.app_id}}}",
                f"AppName={self.app_name}",
                f"AppVersion={app_version}",
                f"AppPublisher={self.publisher}",
                r"DefaultDirName={localappdata}\Programs\GoogleWorkAgent",
                "PrivilegesRequired=lowest",
                "ArchitecturesAllowed=x64compatible",
                "ArchitecturesInstallIn64BitMode=x64compatible",
                "DisableProgramGroupPage=yes",
                "CloseApplications=yes",
                "RestartApplications=no",
                "SetupLogging=yes",
                f"OutputDir={output}",
                f"OutputBaseFilename={filename}",
                "Compression=lzma2",
                "SolidCompression=yes",
                "Uninstallable=yes",
                "",
                "[Files]",
                f'Source: "{source}"; DestDir: "{{app}}"; '
                "Flags: ignoreversion recursesubdirs createallsubdirs",
                "",
                "[Icons]",
                f'Name: "{{autoprograms}}\\{self.app_name}"; Filename: "{{app}}\\{launcher}"',
                "",
                "[UninstallRun]",
                'Filename: "{app}\\uninstaller\\GoogleWorkAgentCredentialCleanup.exe"; '
                'Parameters: "--mode=prompt"; Flags: runhidden waituntilterminated',
                "",
            )
        )


def _inno_quote(value: str) -> str:
    return value.replace('"', '""')


__all__ = ["WindowsInstallerDefinition"]
