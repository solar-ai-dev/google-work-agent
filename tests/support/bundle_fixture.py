from __future__ import annotations

from pathlib import Path

from release.assemble_application_bundle import ApplicationBundleInputs

REPO_ROOT = Path(__file__).resolve().parents[2]


def create_bundle_inputs(
    root: Path,
    *,
    model_manifest: Path | None = None,
) -> ApplicationBundleInputs:
    directories = {
        name: root / name
        for name in (
            "launcher-dist",
            "service-dist",
            "frontend-dist",
            "mcp-dist",
            "runtime-dist",
            "schemas",
            "migrations",
            "uninstaller-dist",
        )
    }
    for directory in directories.values():
        directory.mkdir(parents=True)
    (directories["launcher-dist"] / "GoogleWorkAgentLauncher.exe").write_bytes(b"launcher")
    (directories["service-dist"] / "GoogleWorkAgentService.exe").write_bytes(b"service")
    (directories["frontend-dist"] / "index.html").write_text(
        "<!doctype html><html></html>", encoding="utf-8"
    )
    frontend_assets = directories["frontend-dist"] / "assets"
    frontend_assets.mkdir()
    (frontend_assets / "app.js").write_text("export {};", encoding="utf-8")
    connector_dir = directories["mcp-dist"] / "google_workspace"
    connector_dir.mkdir()
    (connector_dir / "GoogleWorkspaceMcpServer.exe").write_bytes(b"mcp")
    (directories["runtime-dist"] / "python312.dll").write_bytes(b"python-runtime")
    (directories["schemas"] / "openapi-v1.json").write_text("{}", encoding="utf-8")
    (directories["migrations"] / "0001_current_schema.sql").write_text(
        "SELECT 1;", encoding="utf-8"
    )
    (directories["migrations"] / "0019_legacy_v18_adoption.sql").write_text(
        "SELECT 1;", encoding="utf-8"
    )
    (directories["uninstaller-dist"] / "GoogleWorkAgentCredentialCleanup.exe").write_bytes(
        b"credential-cleanup"
    )
    return ApplicationBundleInputs(
        launcher_distribution=directories["launcher-dist"],
        service_distribution=directories["service-dist"],
        frontend_distribution=directories["frontend-dist"],
        mcp_distribution=directories["mcp-dist"],
        runtime_distribution=directories["runtime-dist"],
        schemas=directories["schemas"],
        migrations=directories["migrations"],
        uninstaller_distribution=directories["uninstaller-dist"],
        installed_connector_manifest=(
            REPO_ROOT
            / "src/google_work_agent/adapters/connectors/runtime/installed_connector_manifest.json"
        ),
        signed_tool_registry=(
            REPO_ROOT
            / "src/google_work_agent/application/tool_registry/tool_registry_manifest.json"
        ),
        model_manifest=model_manifest,
    )
