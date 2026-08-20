"""Manifest-enforced MCP transport boundary.

The underlying subprocess transport verifies the executable, manifest hash,
public Agent tool registry, and startup public tool list. This wrapper adds the
separate non-Agent capability surface and performs the final fail-closed
membership check immediately before every tool dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, cast

from google_work_agent.adapters.mcp.capabilities import MCPInternalCapability
from google_work_agent.adapters.mcp.transport import MCPConnectorDescriptor
from google_work_agent.ports import (
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPTransport,
    MCPTransportError,
    MCPTransportErrorCode,
)


class _RestartableManifestDelegate(MCPTransport, Protocol):
    @property
    def service_instance_id(self) -> str: ...

    @property
    def process_instance_id(self) -> str | None: ...

    def sign_claim_context(self, payload: dict[str, object]) -> str: ...

    def restart(self) -> MCPRuntimeMetadata: ...


class ManifestEnforcedMCPTransport:
    """Guard one verified connector transport with an explicit callable surface."""

    def __init__(
        self,
        *,
        delegate: _RestartableManifestDelegate,
        descriptor: MCPConnectorDescriptor,
        expected_internal_capabilities: tuple[MCPInternalCapability, ...],
    ) -> None:
        self._delegate = delegate
        self._descriptor = descriptor
        self._expected_internal_capabilities = expected_internal_capabilities
        self._verified_callable_names = self._load_verified_manifest_surface()
        self._verify_remote_internal_surface()

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        if tool_name not in self._verified_callable_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message=f"tool is outside verified connector capability surface: {tool_name}",
                dispatch_started=False,
            )
        return self._delegate.call_tool(tool_name=tool_name, arguments=arguments)

    def call_control(
        self,
        *,
        method: str,
        arguments: dict[str, object],
    ) -> MCPControlResponse:
        return self._delegate.call_control(method=method, arguments=arguments)

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return self._delegate.runtime_metadata()

    def close(self) -> None:
        self._delegate.close()

    def restart(self) -> MCPRuntimeMetadata:
        metadata = self._delegate.restart()
        self._verify_remote_internal_surface()
        return metadata

    @property
    def service_instance_id(self) -> str:
        return self._delegate.service_instance_id

    @property
    def process_instance_id(self) -> str | None:
        return self._delegate.process_instance_id

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return self._delegate.sign_claim_context(payload)

    def _load_verified_manifest_surface(self) -> frozenset[str]:
        manifest_path = Path(self._descriptor.artifact_config.manifest_path)
        payload = cast(
            dict[str, object],
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )

        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="manifest public tool surface is missing",
            )
        manifest_public_names = tuple(
            sorted(
                str(item["tool_name"])
                for item in raw_tools
                if isinstance(item, dict) and "tool_name" in item
            )
        )
        expected_public_names = tuple(
            entry.tool_name for entry in self._descriptor.expected_tool_registry.list_entries()
        )
        if manifest_public_names != expected_public_names or len(manifest_public_names) != len(
            raw_tools
        ):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest public tool surface changed after transport verification",
            )

        raw_internal = payload.get("internal_capabilities")
        if not isinstance(raw_internal, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="manifest internal capability surface is missing",
            )
        manifest_internal = tuple(
            sorted(
                (
                    str(item.get("tool_name", "")),
                    str(item.get("category", "")),
                    str(item.get("input_schema_version", "")),
                    str(item.get("output_schema_version", "")),
                    str(item.get("registry_version", "")),
                )
                for item in raw_internal
                if isinstance(item, dict)
            )
        )
        expected_internal = tuple(
            sorted(
                (
                    capability.tool_name,
                    capability.category.value,
                    capability.input_schema_version,
                    capability.output_schema_version,
                    capability.registry_version,
                )
                for capability in self._expected_internal_capabilities
            )
        )
        if manifest_internal != expected_internal or len(manifest_internal) != len(raw_internal):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest internal capability contract mismatch",
            )

        public_names = frozenset(manifest_public_names)
        internal_names = frozenset(item[0] for item in manifest_internal)
        if public_names & internal_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="public and internal MCP capability surfaces overlap",
            )
        return public_names | internal_names

    def _verify_remote_internal_surface(self) -> None:
        response = self._delegate.call_control(
            method="mcp.list_internal_capabilities",
            arguments={},
        )
        raw_names = response.payload.get("internal_capability_names")
        if not isinstance(raw_names, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.HANDSHAKE_FAILED,
                message="remote internal capability list is missing",
            )
        remote_names = tuple(sorted(str(name) for name in raw_names))
        expected_names = tuple(
            sorted(capability.tool_name for capability in self._expected_internal_capabilities)
        )
        if remote_names != expected_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="remote internal capability surface mismatch",
            )
