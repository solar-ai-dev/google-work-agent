"""Validated Connector WRITE dispatch through the sole MCP runtime seam."""

from __future__ import annotations

from typing import Literal, cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
    ConnectorWriteResultV1,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort

_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})


class McpConnectorWriteAdapter(ConnectorWritePort):
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

    def execute_write(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
        claim_token: dict[str, JsonValue],
    ) -> ConnectorWriteResultV1:
        if binding.effect not in _WRITE_EFFECTS:
            raise ValueError("ConnectorWritePort requires a WRITE binding")
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
        arguments = dict(tool_arguments)
        arguments["claim_context"] = self._signed_claim_context(claim_token)
        response = self._mcp_client.call_tool(
            binding.connector_id,
            binding.tool_id,
            arguments,
            self._timeout_ms,
        )
        payload = response.payload if isinstance(response.payload, dict) else {}
        metadata = cast(dict[str, JsonValue], payload)
        if response.transport_status == "OK":
            return ConnectorWriteResultV1(
                schema_version=1,
                success=True,
                delivery_certainty=None,
                provider_request_id=_optional_string(metadata.get("request_id")),
                response_metadata=_bounded_metadata(metadata),
                error_code=None,
            )
        certainty = _delivery_certainty(metadata.get("delivery_certainty"))
        return ConnectorWriteResultV1(
            schema_version=1,
            success=False,
            delivery_certainty=certainty,
            provider_request_id=_optional_string(metadata.get("request_id")),
            response_metadata=_bounded_metadata(metadata),
            error_code=response.error_code or "CONNECTOR_WRITE_FAILED",
        )

    def _signed_claim_context(self, claim_token: dict[str, JsonValue]) -> dict[str, JsonValue]:
        process_instance_id = getattr(self._mcp_client, "process_instance_id", None)
        sign = getattr(self._mcp_client, "sign_claim_context", None)
        if not isinstance(process_instance_id, str) or not callable(sign):
            raise RuntimeError("MCP claim signing context is unavailable")
        unsigned = dict(claim_token)
        unsigned["mcp_process_instance_id"] = process_instance_id
        unsigned.pop("signature", None)
        signature = sign(unsigned)
        return {**unsigned, "signature": signature}


def _delivery_certainty(
    value: JsonValue,
) -> Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"]:
    if value == "NOT_SENT":
        return "NOT_SENT"
    if value == "SENT_RESPONSE_LOST":
        return "SENT_RESPONSE_LOST"
    return "MAY_HAVE_BEEN_SENT"


def _optional_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _bounded_metadata(
    payload: dict[str, JsonValue],
) -> dict[str, str | int | float | bool | None]:
    bounded = {
        key: value
        for key, value in payload.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    item = payload.get("item")
    if isinstance(item, dict):
        for key in (
            "fixture_snapshot_id",
            "resource_type",
            "resource_id",
            "parent_id",
            "version",
            "recovery_fingerprint",
        ):
            value = item.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                bounded[key] = value
    return bounded


__all__ = ["McpConnectorWriteAdapter"]
