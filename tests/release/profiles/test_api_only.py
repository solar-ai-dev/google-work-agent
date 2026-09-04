import pytest
from release.profiles.api_only import build_api_only_profile

from release.profiles import DeploymentProfile


def test_api_only_has__no_local_runtime__or_model_dependency() -> None:
    profile = build_api_only_profile()

    assert profile.deployment_profile is DeploymentProfile.API_ONLY
    assert profile.runtime_modes == ("API_LLM",)
    assert profile.requires_model_manifest is False
    assert profile.requires_local_model_profile is False
    assert "manifests/model-manifest-v1.json" not in profile.required_files


def test_api_only__rejects_local__model_manifest() -> None:
    profile = build_api_only_profile()
    paths = profile.required_files + (
        "runtime/python312.dll",
        "schemas/openapi-v1.json",
        "migrations/0001_current_schema.sql",
        "manifests/model-manifest-v1.json",
    )

    with pytest.raises(ValueError, match="API_ONLY must omit"):
        profile.validate(paths)
