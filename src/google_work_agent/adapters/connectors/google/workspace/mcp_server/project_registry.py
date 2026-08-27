"""Load the release-generated Google Workspace MCP descriptor projection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from string import hexdigits
from typing import cast

from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1

_DEFAULT_PROJECTION = Path(__file__).with_name("tool_descriptor_projection.json")
_PROJECTION_PATH_ENV = "GWA_MCP_TOOL_PROJECTION_PATH"
_PROJECTION_FIELDS = frozenset(
    {"schema_version", "connector_id", "registry_manifest_hash", "tools"}
)
_TOOL_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "tool_id",
        "input_schema_ref",
        "output_schema_ref",
        "registry_entry_hash",
    }
)


def project_registry(path: Path | None = None) -> tuple[MCPToolDescriptorV1, ...]:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    decoded = json.loads(projection_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("tool descriptor projection must be an object")
    payload = cast(dict[str, object], decoded)
    _require_exact_fields(payload, _PROJECTION_FIELDS, "tool descriptor projection")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != "google_workspace":
        raise ValueError("invalid Google Workspace MCP projection identity")
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ValueError("tool descriptor projection tools must be a non-empty list")
    tools = tuple(_descriptor(_require_object(item)) for item in raw_tools)
    if len({tool.tool_id for tool in tools}) != len(tools):
        raise ValueError("duplicate tool_id in Google Workspace MCP projection")
    return tuple(sorted(tools, key=lambda tool: tool.tool_id))


def registry_manifest_hash(path: Path | None = None) -> str:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    payload = cast(dict[str, object], json.loads(projection_path.read_text(encoding="utf-8")))
    value = str(payload.get("registry_manifest_hash", ""))
    _validate_hash(value, "registry_manifest_hash")
    return value


def get_projected_tool(tool_id: str) -> MCPToolDescriptorV1 | None:
    return next((tool for tool in project_registry() if tool.tool_id == tool_id), None)


def _descriptor(payload: dict[str, object]) -> MCPToolDescriptorV1:
    _require_exact_fields(payload, _TOOL_FIELDS, "MCPToolDescriptorV1")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != "google_workspace":
        raise ValueError("invalid projected tool identity")
    _validate_hash(str(payload.get("registry_entry_hash", "")), "registry_entry_hash")
    return MCPToolDescriptorV1(
        schema_version=cast(int, payload["schema_version"]),  # type: ignore[arg-type]
        connector_id=str(payload["connector_id"]),
        tool_id=str(payload["tool_id"]),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        registry_entry_hash=str(payload["registry_entry_hash"]),
    )


def _require_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("MCPToolDescriptorV1 must be an object")
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


def _validate_hash(value: str, field_name: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in hexdigits for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


__all__ = ["get_projected_tool", "project_registry", "registry_manifest_hash"]
