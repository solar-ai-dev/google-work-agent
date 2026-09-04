"""LOCAL_CAPABLE release profile authority."""

from __future__ import annotations

from dataclasses import replace

from release.profiles import DeploymentProfile, ReleaseArtifactProfile
from release.profiles.api_only import build_api_only_profile


def build_local_capable_profile() -> ReleaseArtifactProfile:
    """Extend the common profile only with the signed local-model allowlist."""

    common = build_api_only_profile()
    return replace(
        common,
        deployment_profile=DeploymentProfile.LOCAL_CAPABLE,
        runtime_modes=("API_LLM", "LOCAL_GPU", "AUTO"),
        requires_model_manifest=True,
        requires_local_model_product_decision=True,
        requires_local_model_profile=True,
    )


__all__ = ["build_local_capable_profile"]
