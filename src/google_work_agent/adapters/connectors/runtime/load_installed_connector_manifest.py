"""Installed Connector process-binding manifest loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, cast

_IMPLEMENTATION_MANIFEST = Path(__file__).with_name("installed_connector_manifest.json")
_MANIFEST_FIELDS = frozenset({"schema_version", "connectors"})
_ENTRY_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "provider_namespace",
        "connector_package",
        "executable_path",
        "tool_projection_path",
        "mcp_schema_version",
    }
)


@dataclass(frozen=True, slots=True)
class InstalledConnectorEntryV1:
    schema_version: Literal[1]
    connector_id: str
    provider_namespace: str
    connector_package: str
    executable_path: str
    tool_projection_path: str
    mcp_schema_version: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported InstalledConnectorEntryV1 schema_version")
        if not self.connector_id.strip():
            raise ValueError("connector_id is required")
        for field_name in ("provider_namespace", "connector_package", "mcp_schema_version"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        _validate_relative_artifact_path(self.executable_path)
        _validate_relative_artifact_path(self.tool_projection_path)


@dataclass(frozen=True, slots=True)
class InstalledConnectorManifestV1:
    schema_version: Literal[1]
    connectors: tuple[InstalledConnectorEntryV1, ...]

    def get_required(self, connector_id: str) -> InstalledConnectorEntryV1:
        try:
            return next(entry for entry in self.connectors if entry.connector_id == connector_id)
        except StopIteration as error:
            raise LookupError(f"installed connector not registered: {connector_id}") from error


def load_installed_connector_manifest(
    path: Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> InstalledConnectorManifestV1:
    manifest_path = _IMPLEMENTATION_MANIFEST if path is None else path
    manifest_bytes = manifest_path.read_bytes()
    if expected_sha256 is not None and sha256(manifest_bytes).hexdigest() != expected_sha256:
        raise ValueError("Installed Connector manifest release hash mismatch")
    decoded = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    if not isinstance(decoded, dict):
        raise ValueError("InstalledConnectorManifestV1 must be an object")
    payload = cast(dict[str, object], decoded)
    _require_exact_fields(payload, _MANIFEST_FIELDS, "InstalledConnectorManifestV1")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported InstalledConnectorManifestV1 schema_version")
    raw_connectors = payload.get("connectors")
    if not isinstance(raw_connectors, list) or not raw_connectors:
        raise ValueError("connectors must be a non-empty list")
    connectors = tuple(_entry(_require_object(item)) for item in raw_connectors)
    connector_ids = [entry.connector_id for entry in connectors]
    if len(connector_ids) != len(set(connector_ids)):
        raise ValueError("installed connector manifest contains duplicate connector_id")
    return InstalledConnectorManifestV1(schema_version=1, connectors=connectors)


def _entry(payload: dict[str, object]) -> InstalledConnectorEntryV1:
    _require_exact_fields(payload, _ENTRY_FIELDS, "InstalledConnectorEntryV1")
    if payload.get("schema_version") != 1 or any(
        not isinstance(payload.get(field), str)
        for field in _ENTRY_FIELDS - {"schema_version"}
    ):
        raise ValueError("InstalledConnectorEntryV1 field type mismatch")
    return InstalledConnectorEntryV1(
        schema_version=cast(int, payload["schema_version"]),  # type: ignore[arg-type]
        connector_id=str(payload["connector_id"]),
        provider_namespace=str(payload["provider_namespace"]),
        connector_package=str(payload["connector_package"]),
        executable_path=str(payload["executable_path"]),
        tool_projection_path=str(payload["tool_projection_path"]),
        mcp_schema_version=str(payload["mcp_schema_version"]),
    )


def _validate_relative_artifact_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ValueError("installed connector artifact path must be safe and relative")


def _require_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("InstalledConnectorEntryV1 must be an object")
    return cast(dict[str, object], value)


def _require_exact_fields(
    payload: dict[str, object], expected: frozenset[str], contract_name: str
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise ValueError(
            f"{contract_name} fields mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate installed connector manifest field: {key}")
        result[key] = value
    return result


__all__ = [
    "InstalledConnectorEntryV1",
    "InstalledConnectorManifestV1",
    "load_installed_connector_manifest",
]
