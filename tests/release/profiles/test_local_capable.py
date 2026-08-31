import pytest
from release.profiles.local_capable import build_local_capable_profile

from release.profiles import DeploymentProfile


def test_local_capable_extends_common_profile_only_with_local_allowlist() -> None:
    profile = build_local_capable_profile()

    assert profile.deployment_profile is DeploymentProfile.LOCAL_CAPABLE
    assert profile.runtime_modes == ("API_LLM", "LOCAL_GPU", "AUTO")
    assert profile.requires_model_manifest is True
    assert all("ollama" not in path.lower() for path in profile.required_files)


def test_local_capable_fails_closed_without_model_manifest() -> None:
    profile = build_local_capable_profile()
    paths = profile.required_files + (
        "runtime/python312.dll",
        "schemas/openapi-v1.json",
        "migrations/0001_initial.sql",
    )

    with pytest.raises(ValueError, match="LOCAL_CAPABLE requires"):
        profile.validate(paths)
