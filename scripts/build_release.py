"""Thin CLI wrapper for the canonical one-folder bundle assembler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for import_root in (REPO_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from release.assemble_application_bundle import (  # noqa: E402
    ApplicationBundleInputs,
    assemble_application_bundle,
)

from release.profiles import DeploymentProfile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in DeploymentProfile],
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--launcher-dist", type=Path, required=True)
    parser.add_argument("--service-dist", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--mcp-dist", type=Path, required=True)
    parser.add_argument("--runtime-dist", type=Path, required=True)
    parser.add_argument("--schemas-dir", type=Path, required=True)
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=REPO_ROOT / "src/google_work_agent/adapters/persistence/migrations",
    )
    parser.add_argument("--uninstaller-dist", type=Path, required=True)
    parser.add_argument(
        "--installed-connector-manifest",
        type=Path,
        default=REPO_ROOT
        / "src/google_work_agent/adapters/connectors/runtime/installed_connector_manifest.json",
    )
    parser.add_argument(
        "--signed-tool-registry",
        type=Path,
        default=(
            REPO_ROOT
            / "src/google_work_agent/application/tool_registry/tool_registry_manifest.json"
        ),
    )
    parser.add_argument("--model-manifest", type=Path)
    arguments = parser.parse_args()
    output = arguments.output_dir.resolve()
    assemble_application_bundle(
        profile=DeploymentProfile(arguments.profile),
        inputs=ApplicationBundleInputs(
            launcher_distribution=arguments.launcher_dist.resolve(),
            service_distribution=arguments.service_dist.resolve(),
            frontend_distribution=arguments.frontend_dist.resolve(),
            mcp_distribution=arguments.mcp_dist.resolve(),
            runtime_distribution=arguments.runtime_dist.resolve(),
            schemas=arguments.schemas_dir.resolve(),
            migrations=arguments.migrations_dir.resolve(),
            uninstaller_distribution=arguments.uninstaller_dist.resolve(),
            installed_connector_manifest=arguments.installed_connector_manifest.resolve(),
            signed_tool_registry=arguments.signed_tool_registry.resolve(),
            model_manifest=(
                arguments.model_manifest.resolve() if arguments.model_manifest is not None else None
            ),
        ),
        output_root=output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
