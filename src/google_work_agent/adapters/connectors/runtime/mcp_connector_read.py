"""Validated Connector READ dispatch through the sole MCP runtime seam."""

from __future__ import annotations

from typing import cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort


class McpConnectorReadAdapter(ConnectorReadPort):
    def __init__(
        self,
        *,
        runtime_registry: ConnectorRuntimeRegistry,
        mcp_client: MCPClientPort,
        timeout_ms: int = 30_000,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._mcp_client = mcp_client
        self._timeout_ms = timeout_ms

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        if binding.effect != "READ":
            raise ValueError("ConnectorReadPort requires a READ binding")
        self._runtime_registry.resolve(binding.connector_id)
        descriptors = {
            descriptor.tool_id: descriptor
            for descriptor in self._mcp_client.list_tools(binding.connector_id)
        }
        descriptor = descriptors.get(binding.tool_id)
        if descriptor is None or (
            descriptor.connector_id,
            descriptor.input_schema_ref,
            descriptor.output_schema_ref,
            descriptor.registry_entry_hash,
        ) != (
            binding.connector_id,
            binding.input_schema_ref,
            binding.output_schema_ref,
            binding.registry_entry_hash,
        ):
            raise ValueError("validated Connector Tool binding does not match MCP descriptor")
        response = self._mcp_client.call_tool(
            binding.connector_id,
            binding.tool_id,
            tool_arguments,
            self._timeout_ms,
        )
        if response.transport_status != "OK" or not isinstance(response.payload, dict):
            raise RuntimeError(response.error_code or "CONNECTOR_READ_FAILED")
        output = cast(dict[str, JsonValue], response.payload)
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id=str(output.get("request_id", "")),
            output=output,
            next_page_token=_optional_string(output.get("next_page_token")),
            total_count=_optional_int(output.get("total_count")),
        )


def _optional_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["McpConnectorReadAdapter"]
