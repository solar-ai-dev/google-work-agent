"""Thin CLI wrapper for the canonical one-folder bundle assembler."""

from __future__ import annotations

import argparse
import os
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
from release.build_windows_installer import (  # noqa: E402
    InnoSetupBackend,
    build_windows_installer,
    discover_inno_setup_backend,
)
from release.generate_release_manifest import ReleaseManifestParameters  # noqa: E402
from release.sign_release_artifacts import (  # noqa: E402
    Ed25519PemManifestSigner,
    WindowsSignToolBackend,
    sign_release_artifacts,
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
    parser.add_argument("--app-version", required=True)
    parser.add_argument(
        "--build-channel", choices=("DEVELOPMENT", "STAGING", "PRODUCTION"), required=True
    )
    parser.add_argument(
        "--oauth-env", choices=("DEVELOPMENT", "STAGING", "PRODUCTION"), required=True
    )
    parser.add_argument("--oauth-client-id", required=True)
    parser.add_argument("--api-contract-version", required=True)
    parser.add_argument("--mcp-schema-version", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--database-migration-version", required=True)
    parser.add_argument("--manifest-private-key", type=Path, required=True)
    parser.add_argument("--embedded-release-public-key", type=Path, required=True)
    parser.add_argument("--timestamp-url")
    parser.add_argument("--signtool", type=Path)
    parser.add_argument("--certificate-selector", action="append", default=[])
    parser.add_argument("--inno-setup", type=Path)
    parser.add_argument("--installer-output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    migrations = arguments.migrations_dir.resolve()
    migration_versions = tuple(
        sorted(
            {
                path.name.partition("_")[0]
                for path in migrations.glob("*.sql")
                if path.name.partition("_")[0].isdigit()
            }
        )
    )
    if not migration_versions:
        raise ValueError("release bundle requires at least one database migration")
    if arguments.database_migration_version != migration_versions[-1]:
        raise ValueError(
            "database migration version must match the latest packaged migration: "
            f"{migration_versions[-1]}"
        )
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
            migrations=migrations,
            uninstaller_distribution=arguments.uninstaller_dist.resolve(),
            installed_connector_manifest=arguments.installed_connector_manifest.resolve(),
            signed_tool_registry=arguments.signed_tool_registry.resolve(),
            model_manifest=(
                arguments.model_manifest.resolve() if arguments.model_manifest is not None else None
            ),
        ),
        output_root=output,
    )
    password = os.environ.get("GWA_MANIFEST_SIGNING_KEY_PASSWORD")
    manifest_signer = Ed25519PemManifestSigner(
        arguments.manifest_private_key.resolve(),
        None if password is None else password.encode("utf-8"),
    )
    embedded_public_key = arguments.embedded_release_public_key.read_bytes()
    distributed = arguments.build_channel in {"STAGING", "PRODUCTION"}
    if distributed and (arguments.signtool is None or not arguments.timestamp_url):
        raise ValueError("distributed release requires signtool and timestamp URL")
    code_signer = (
        None
        if arguments.signtool is None
        else WindowsSignToolBackend(
            arguments.signtool.resolve(), tuple(arguments.certificate_selector)
        )
    )
    code_artifacts = tuple(
        path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    )
    parameters = ReleaseManifestParameters(
        app_version=arguments.app_version,
        build_channel=arguments.build_channel,
        deployment_profile=DeploymentProfile(arguments.profile),
        oauth_env=arguments.oauth_env,
        oauth_client_id=arguments.oauth_client_id,
        api_contract_version=arguments.api_contract_version,
        mcp_schema_version=arguments.mcp_schema_version,
        policy_version=arguments.policy_version,
        database_migration_version=arguments.database_migration_version,
    )
    sign_release_artifacts(
        code_artifacts=code_artifacts,
        distribution_kind=arguments.build_channel,
        code_signer=code_signer,
        timestamp_url=arguments.timestamp_url,
        bundle_root=output,
        manifest_parameters=parameters,
        manifest_signer=manifest_signer,
        embedded_release_public_key_pem=embedded_public_key,
    )
    installer_backend = (
        InnoSetupBackend(arguments.inno_setup.resolve())
        if arguments.inno_setup is not None
        else discover_inno_setup_backend()
    )
    installer = build_windows_installer(
        bundle_root=output,
        output_dir=arguments.installer_output_dir.resolve(),
        trusted_release_public_key_pem=embedded_public_key,
        backend=installer_backend,
        code_signature_verifier=code_signer,
    )
    sign_release_artifacts(
        code_artifacts=(installer,),
        distribution_kind=arguments.build_channel,
        code_signer=code_signer,
        timestamp_url=arguments.timestamp_url,
    )
    if code_signer is not None and not code_signer.verify(installer, require_timestamp=distributed):
        raise RuntimeError("signed installer verification failed")
    print(installer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
