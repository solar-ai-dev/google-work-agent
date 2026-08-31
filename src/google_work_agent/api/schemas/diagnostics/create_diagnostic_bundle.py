"""Canonical sanitized diagnostic-bundle wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class CreateDiagnosticBundleRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str
    scope: Literal["LAST_24H", "RUN"]
    run_id: str | None = None


class DiagnosticBundleMetadataResponseV1(ApiModel):
    schema_version: Literal[1]
    bundle_ref: str
    scope: Literal["LAST_24H", "RUN"]
    created_at_ms: int
    size_bytes: int


__all__ = ["CreateDiagnosticBundleRequestV1", "DiagnosticBundleMetadataResponseV1"]
