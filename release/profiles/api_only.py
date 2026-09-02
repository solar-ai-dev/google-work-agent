"""API_ONLY release profile authority."""

from __future__ import annotations

from release.profiles import DeploymentProfile, ReleaseArtifactProfile

_COMMON_REQUIRED_FILES = (
    "launcher/GoogleWorkAgentLauncher.exe",
    "service/GoogleWorkAgentService.exe",
    "frontend/index.html",
    "mcp/google_workspace/GoogleWorkspaceMcpServer.exe",
    "manifests/installed-connectors-v1.json",
    "manifests/signed-tool-registry-v1.json",
    "manifests/connectors/google_workspace/tool-descriptor-projection-v1.json",
    "uninstaller/GoogleWorkAgentCredentialCleanup.exe",
    "uninstaller/installer-definition-v1.json",
    "uninstaller/uninstall-policy-v1.json",
    "uninstaller/upgrade-policy-v1.json",
)

_COMMON_NONEMPTY_DIRECTORIES = (
    "launcher",
    "service",
    "frontend",
    "mcp",
    "runtime",
    "schemas",
    "migrations",
    "manifests",
    "uninstaller",
)


def build_api_only_profile() -> ReleaseArtifactProfile:
    """Return the closed API-backed profile without local-model authority."""

    return ReleaseArtifactProfile(
        deployment_profile=DeploymentProfile.API_ONLY,
        runtime_modes=("API_LLM",),
        requires_model_manifest=False,
        requires_local_model_product_decision=False,
        required_files=_COMMON_REQUIRED_FILES,
        required_nonempty_directories=_COMMON_NONEMPTY_DIRECTORIES,
    )


__all__ = ["build_api_only_profile"]
