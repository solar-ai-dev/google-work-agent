"""Build a reproducible one-folder Windows release layout."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from google_work_agent.adapters.runtime import (  # noqa: E402
    ArtifactRecord,
    BuildArtifactType,
    BuildProfile,
    ProductProgramLayout,
    SignedBuildManifest,
)
from google_work_agent.adapters.runtime.build_manifest import hash_file  # noqa: E402

FORBIDDEN_NAMES = {
    ".env",
    "node.exe",
    "npm",
    "npm.cmd",
}
FORBIDDEN_SUFFIXES = {".map", ".pyc"}
FORBIDDEN_PARTS = {"__pycache__", "tests", "experiments"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=[item.value for item in BuildProfile],
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "build" / "release"),
    )
    args = parser.parse_args()

    profile = BuildProfile(args.profile)
    output_dir = Path(args.output_dir).resolve() / profile.value.lower()
    build_release(profile=profile, output_dir=output_dir)
    print(str(output_dir))
    return 0


def build_release(*, profile: BuildProfile, output_dir: Path) -> SignedBuildManifest:
    return build_release_from(
        profile=profile,
        output_dir=output_dir,
        frontend_dist=REPO_ROOT / "frontend" / "dist",
    )


def build_release_from(
    *,
    profile: BuildProfile,
    output_dir: Path,
    frontend_dist: Path,
) -> SignedBuildManifest:
    if not frontend_dist.exists():
        raise RuntimeError("frontend/dist is missing; run frontend build first")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    layout = ProductProgramLayout.from_root(output_dir)
    for directory in (
        layout.launcher_dir,
        layout.service_dir,
        layout.frontend_dir,
        layout.mcp_dir,
        layout.runtime_dir,
        layout.schemas_dir,
        layout.migrations_dir,
        layout.manifests_dir,
        layout.uninstaller_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _copy_tree(SRC_ROOT / "google_work_agent", layout.service_dir / "google_work_agent")
    _copy_tree(SRC_ROOT / "google_work_agent", layout.mcp_dir / "google_work_agent")
    _copy_tree(frontend_dist, layout.frontend_dir)
    _copy_tree(
        SRC_ROOT / "google_work_agent" / "adapters" / "persistence" / "migrations",
        layout.migrations_dir,
    )
    (layout.schemas_dir / "placeholder.json").write_text("{}", encoding="utf-8")
    (layout.runtime_dir / f"profile-{profile.value.lower()}.json").write_text(
        json.dumps(_runtime_profile_payload(profile), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if profile is BuildProfile.LOCAL_CAPABLE:
        (layout.runtime_dir / "approved-models.json").write_text(
            json.dumps(_approved_models_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    service_script = layout.service_dir / "google_work_agent_service.py"
    mcp_script = layout.mcp_dir / "google_work_agent_mcp.py"
    launcher_script = layout.launcher_dir / "google_work_agent_launcher.pyw"
    uninstall_script = layout.uninstaller_dir / "uninstall.py"
    service_script.write_text(_service_entrypoint(), encoding="utf-8")
    mcp_script.write_text(_mcp_entrypoint(), encoding="utf-8")
    launcher_script.write_text(_launcher_entrypoint(), encoding="utf-8")
    uninstall_script.write_text(_uninstall_entrypoint(), encoding="utf-8")

    frontend_hashes = _relative_hashes(layout.frontend_dir)
    runtime_components = tuple(
        _artifact_record(output_dir, path, BuildArtifactType.DATA)
        for path in sorted(_iter_files(output_dir))
        if path not in {service_script, mcp_script}
    )
    manifest = SignedBuildManifest(
        schema_version=1,
        product_name="GoogleWorkAgent",
        release_version="0.1.0",
        build_id=f"build-{profile.value.lower()}",
        build_profile=profile,
        api_contract_version="1",
        domain_contract_version="1",
        database_schema_version="1",
        frontend_manifest_version="1",
        frontend_asset_hashes=frontend_hashes,
        service_artifact=_artifact_record(output_dir, service_script, BuildArtifactType.EXECUTABLE),
        mcp_artifact=_artifact_record(output_dir, mcp_script, BuildArtifactType.EXECUTABLE),
        runtime_components=runtime_components,
        mcp_manifest_version="1",
        tool_registry_version="1",
        created_at_ms=0,
    )
    manifest_path = layout.manifests_dir / "build-manifest.json"
    manifest_path.write_text(manifest.to_canonical_json(), encoding="utf-8")
    return manifest


def _copy_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _skip_path(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _skip_path(relative: Path) -> bool:
    if any(part in FORBIDDEN_PARTS for part in relative.parts):
        return True
    if relative.name in FORBIDDEN_NAMES:
        return True
    return relative.suffix in FORBIDDEN_SUFFIXES


def _relative_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): hash_file(path)
        for path in sorted(_iter_files(root))
    }


def _artifact_record(root: Path, path: Path, artifact_type: BuildArtifactType) -> ArtifactRecord:
    return ArtifactRecord(
        relative_install_path=str(path.relative_to(root)).replace("\\", "/"),
        sha256=hash_file(path),
        size_bytes=path.stat().st_size,
        artifact_type=artifact_type,
        executable=path.suffix in {".py", ".pyw"},
        required=True,
    )


def _iter_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not _skip_path(path.relative_to(root))
    ]


def _runtime_profile_payload(profile: BuildProfile) -> dict[str, object]:
    if profile is BuildProfile.API_ONLY:
        return {
            "profile": profile.value,
            "available_runtime_modes": ["API_LLM"],
            "local_runtime_enabled": False,
            "approved_model_manifest": None,
        }
    return {
        "profile": profile.value,
        "available_runtime_modes": ["API_LLM", "LOCAL_GPU", "AUTO"],
        "local_runtime_enabled": True,
        "approved_model_manifest": "runtime/approved-models.json",
    }


def _approved_models_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "models": [
            {
                "model_id": "approved-model",
                "runtime": "OLLAMA",
                "manifest_version": "1",
                "minimum_runtime_version": "0.1.0",
            }
        ],
    }


def _service_entrypoint() -> str:
    return (
        "from google_work_agent.api import create_app\nraise SystemExit('service packaging stub')\n"
    )


def _mcp_entrypoint() -> str:
    return (
        "from google_work_agent.adapters.connectors.google.mcp.verified_server import main\n"
        "raise SystemExit('mcp packaging stub')\n"
    )


def _launcher_entrypoint() -> str:
    return "from launcher.entrypoint import main\nraise SystemExit(main())\n"


def _uninstall_entrypoint() -> str:
    return "raise SystemExit('uninstall hook placeholder')\n"


if __name__ == "__main__":
    raise SystemExit(main())
