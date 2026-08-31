"""Project signed-locked build fields from an already verified manifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from launcher.verify_installation import VerifiedInstallation


@dataclass(frozen=True, slots=True)
class SignedBuildConfigV1:
    schema_version: Literal[1]
    app_version: str
    build_channel: str
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"]
    oauth_env: Literal["DEVELOPMENT", "STAGING", "PRODUCTION"]
    oauth_client_id: str
    api_contract_version: str
    mcp_schema_version: str
    policy_version: str
    database_migration_version: str


def load_signed_build_config(installation: VerifiedInstallation) -> SignedBuildConfigV1:
    """Return only fields authenticated by ``verify_installation``."""

    manifest = installation.manifest
    return SignedBuildConfigV1(
        schema_version=1,
        app_version=_string(manifest, "app_version"),
        build_channel=_string(manifest, "build_channel"),
        deployment_profile=cast(
            Literal["API_ONLY", "LOCAL_CAPABLE"], manifest["deployment_profile"]
        ),
        oauth_env=cast(
            Literal["DEVELOPMENT", "STAGING", "PRODUCTION"], manifest["oauth_env"]
        ),
        oauth_client_id=_string(manifest, "oauth_client_id"),
        api_contract_version=_string(manifest, "api_contract_version"),
        mcp_schema_version=_string(manifest, "mcp_schema_version"),
        policy_version=_string(manifest, "policy_version"),
        database_migration_version=_string(manifest, "database_migration_version"),
    )


def _string(manifest: Mapping[str, object], field: str) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"verified manifest field is invalid: {field}")
    return value
