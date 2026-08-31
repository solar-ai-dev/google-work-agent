import pytest
from release.profiles.api_only import build_api_only_profile

from release.profiles import DeploymentProfile


def test_api_only_has_no_local_runtime_or_model_dependency() -> None:
    profile = build_api_only_profile()

    assert profile.deployment_profile is DeploymentProfile.API_ONLY
    assert profile.runtime_modes == ("API_LLM",)
    assert profile.requires_model_manifest is False
    assert "manifests/model-manifest-v1.json" not in profile.required_files


def test_api_only_rejects_local_model_manifest() -> None:
    profile = build_api_only_profile()
    paths = profile.required_files + (
        "runtime/python312.dll",
        "schemas/openapi-v1.json",
        "migrations/0001_initial.sql",
        "manifests/model-manifest-v1.json",
    )

    with pytest.raises(ValueError, match="API_ONLY must omit"):
        profile.validate(paths)
