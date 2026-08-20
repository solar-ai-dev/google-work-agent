"""Manifest-enforced MCP transport boundary.

Public Agent tools and non-Agent capabilities stay separate, but both must be
present in the verified manifest. Actual input/output schemas are verified
against the connector schema authority, and every tool call rechecks the
negotiated manifest/registry versions immediately before delegate dispatch.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from google_work_agent.adapters.mcp.capabilities import MCPInternalCapability
from google_work_agent.adapters.mcp.transport import MCPConnectorDescriptor
from google_work_agent.domain.google_workspace_tool_contracts import (
    google_workspace_tool_contract,
)
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
        self._internal_registry_version = _single_internal_registry_version(
            expected_internal_capabilities
        )
        self._verified_callable_names = self._load_verified_manifest_surface()
        self._verify_remote_internal_surface()
        self._verify_remote_contract_surface()

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        self._require_current_callable(tool_name)
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
        self._verify_remote_contract_surface()
        return metadata

    @property
    def service_instance_id(self) -> str:
        return self._delegate.service_instance_id

    @property
    def process_instance_id(self) -> str | None:
        return self._delegate.process_instance_id

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return self._delegate.sign_claim_context(payload)

    def _require_current_callable(self, tool_name: str) -> None:
        if tool_name not in self._verified_callable_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message=f"tool is outside verified connector capability surface: {tool_name}",
                dispatch_started=False,
            )
        metadata = self._delegate.runtime_metadata()
        config = self._descriptor.artifact_config
        if (
            metadata.manifest_version != config.expected_manifest_version
            or metadata.protocol_version != config.expected_protocol_version
            or metadata.tool_registry_version != config.expected_tool_registry_version
        ):
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="MCP negotiated manifest/registry version is stale",
                dispatch_started=False,
            )

    def _load_verified_manifest_surface(self) -> frozenset[str]:
        manifest_path = Path(self._descriptor.artifact_config.manifest_path)
        raw = manifest_path.read_bytes()
        if sha256(raw).hexdigest() != self._descriptor.artifact_config.expected_manifest_sha256:
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="manifest changed after transport verification",
            )
        payload = cast(dict[str, object], json.loads(raw.decode("utf-8")))
        public_names = self._verify_public_manifest_tools(payload)
        internal_names = self._verify_internal_manifest_capabilities(payload)
        if public_names & internal_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="public and internal MCP capability surfaces overlap",
            )
        return public_names | internal_names

    def _verify_public_manifest_tools(self, payload: dict[str, object]) -> frozenset[str]:
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="manifest public tool surface is missing",
            )
        expected_names = tuple(
            entry.tool_name for entry in self._descriptor.expected_tool_registry.list_entries()
        )
        actual_names: list[str] = []
        for raw_item in raw_tools:
            if not isinstance(raw_item, dict):
                raise MCPTransportError(
                    code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                    message="manifest public tool entry is malformed",
                )
            item = cast(dict[str, object], raw_item)
            tool_name = str(item.get("tool_name", ""))
            actual_names.append(tool_name)
            try:
                registry_entry = self._descriptor.expected_tool_registry.require(tool_name)
                contract = google_workspace_tool_contract(tool_name)
            except (KeyError, LookupError) as error:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.TOOL_REJECTED,
                    message=f"manifest public tool is not registered: {tool_name}",
                ) from error
            if (
                item.get("input_schema_version") != contract.input_schema_version
                or item.get("output_schema_version") != contract.output_schema_version
                or item.get("tool_schema_hash") != contract.schema_hash
                or item.get("tool_schema_hash") != registry_entry.tool_schema_hash
                or item.get("input_schema") != contract.input_schema
                or item.get("output_schema") != contract.output_schema
            ):
                raise MCPTransportError(
                    code=MCPTransportErrorCode.TOOL_REJECTED,
                    message=f"manifest public tool schema mismatch: {tool_name}",
                )
        if tuple(sorted(actual_names)) != expected_names or len(actual_names) != len(set(actual_names)):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest public tool surface mismatch",
            )
        return frozenset(actual_names)

    def _verify_internal_manifest_capabilities(
        self,
        payload: dict[str, object],
    ) -> frozenset[str]:
        if payload.get("internal_capability_registry_version") != self._internal_registry_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest internal capability registry version mismatch",
            )
        raw_internal = payload.get("internal_capabilities")
        if not isinstance(raw_internal, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="manifest internal capability surface is missing",
            )
        expected = {
            capability.tool_name: capability.to_manifest_payload()
            for capability in self._expected_internal_capabilities
        }
        actual_names: list[str] = []
        for raw_item in raw_internal:
            if not isinstance(raw_item, dict):
                raise MCPTransportError(
                    code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                    message="manifest internal capability entry is malformed",
                )
            item = cast(dict[str, object], raw_item)
            tool_name = str(item.get("tool_name", ""))
            actual_names.append(tool_name)
            if expected.get(tool_name) != item:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.TOOL_REJECTED,
                    message=f"manifest internal capability mismatch: {tool_name}",
                )
        if len(actual_names) != len(set(actual_names)) or set(actual_names) != set(expected):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest internal capability surface mismatch",
            )
        return frozenset(actual_names)

    def _verify_remote_internal_surface(self) -> None:
        response = self._delegate.call_control(
            method="mcp.list_internal_capabilities",
            arguments={},
        )
        if response.payload.get("internal_capability_registry_version") != (
            self._internal_registry_version
        ):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="remote internal capability registry version mismatch",
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

    def _verify_remote_contract_surface(self) -> None:
        response = self._delegate.call_control(
            method="mcp.list_capability_contracts",
            arguments={},
        )
        raw_contracts = response.payload.get("contracts")
        if not isinstance(raw_contracts, list):
            raise MCPTransportError(
                code=MCPTransportErrorCode.HANDSHAKE_FAILED,
                message="remote MCP capability contract list is missing",
            )
        expected = self._expected_contract_descriptors()
        actual: list[tuple[str, str, str, str, str]] = []
        for raw_item in raw_contracts:
            if not isinstance(raw_item, dict):
                raise MCPTransportError(
                    code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                    message="remote MCP capability contract is malformed",
                )
            item = cast(dict[str, object], raw_item)
            actual.append(
                (
                    str(item.get("tool_name", "")),
                    str(item.get("category", "")),
                    str(item.get("input_schema_version", "")),
                    str(item.get("output_schema_version", "")),
                    str(item.get("tool_schema_hash", "")),
                )
            )
        if tuple(sorted(actual)) != expected or len(actual) != len(set(actual)):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="remote MCP capability schema surface mismatch",
            )

    def _expected_contract_descriptors(self) -> tuple[tuple[str, str, str, str, str], ...]:
        internal_categories = {
            capability.tool_name: capability.category.value
            for capability in self._expected_internal_capabilities
        }
        descriptors: list[tuple[str, str, str, str, str]] = []
        for tool_name in sorted(self._verified_callable_names):
            contract = google_workspace_tool_contract(tool_name)
            descriptors.append(
                (
                    tool_name,
                    internal_categories.get(tool_name, "AGENT_TOOL"),
                    contract.input_schema_version,
                    contract.output_schema_version,
                    contract.schema_hash,
                )
            )
        return tuple(descriptors)


def _single_internal_registry_version(
    capabilities: tuple[MCPInternalCapability, ...],
) -> str:
    versions = {capability.registry_version for capability in capabilities}
    if len(versions) != 1:
        raise ValueError("internal MCP capabilities must share exactly one registry version")
    return next(iter(versions))
