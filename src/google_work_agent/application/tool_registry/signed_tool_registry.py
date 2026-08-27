"""Canonical signed Connector Tool semantic registry."""

from __future__ import annotations

import json
from hashlib import sha256

from google_work_agent.application.tool_registry.contracts import SignedToolRegistryEntryV1
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1
from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1

DEFAULT_POLICY_VERSION = "2026-08-06.p0"
P0_GOOGLE_WORKSPACE_CONNECTOR_ID = "google_workspace"


class SignedToolRegistry:
    """Immutable lookup and binding authority loaded from the signed manifest."""

    def __init__(
        self,
        entries: tuple[SignedToolRegistryEntryV1, ...],
        *,
        contract_version: str = DEFAULT_POLICY_VERSION,
    ) -> None:
        indexed = {(entry.connector_id, entry.tool_id): entry for entry in entries}
        if len(indexed) != len(entries):
            raise ValueError("tool registry contains duplicate connector_id/tool_id values")
        self._entries = indexed
        self._contract_version = contract_version

    @property
    def contract_version(self) -> str:
        return self._contract_version

    @property
    def entries(self) -> tuple[SignedToolRegistryEntryV1, ...]:
        return tuple(
            sorted(self._entries.values(), key=lambda item: (item.connector_id, item.tool_id))
        )

    @property
    def entries_hash(self) -> str:
        payload = [entry.to_manifest_value() for entry in self.entries]
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return sha256(serialized).hexdigest()

    def get_required(self, connector_id: str, tool_id: str) -> SignedToolRegistryEntryV1:
        try:
            return self._entries[(connector_id, tool_id)]
        except KeyError as error:
            raise LookupError(f"tool not registered: {connector_id}/{tool_id}") from error

    def select_candidates(
        self,
        connector_id: str,
        resource_type: str,
        effect: str,
    ) -> tuple[SignedToolRegistryEntryV1, ...]:
        normalized_resource_type = resource_type.lower()
        return tuple(
            entry
            for entry in self.entries
            if entry.connector_id == connector_id
            and entry.resource_type == normalized_resource_type
            and entry.effect == effect
        )

    def bind_required(
        self,
        connector_id: str,
        tool_id: str,
        expected_effect: str,
    ) -> ValidatedConnectorToolBindingV1:
        entry = self.get_required(connector_id, tool_id)
        if entry.effect != expected_effect:
            raise ValueError(
                "tool effect mismatch: "
                f"{connector_id}/{tool_id} expected={expected_effect} actual={entry.effect}"
            )
        return ValidatedConnectorToolBindingV1(
            schema_version=1,
            connector_id=entry.connector_id,
            resource_type=entry.resource_type,
            tool_id=entry.tool_id,
            effect=entry.effect,
            input_schema_ref=entry.input_schema_ref,
            output_schema_ref=entry.output_schema_ref,
            registry_entry_hash=entry.registry_entry_hash,
        )

    def descriptor_expectations(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        return [
            MCPToolDescriptorV1(
                schema_version=1,
                connector_id=entry.connector_id,
                tool_id=entry.tool_id,
                input_schema_ref=entry.input_schema_ref,
                output_schema_ref=entry.output_schema_ref,
                registry_entry_hash=entry.registry_entry_hash,
            )
            for entry in self.entries
            if entry.connector_id == connector_id
        ]


__all__ = [
    "DEFAULT_POLICY_VERSION",
    "P0_GOOGLE_WORKSPACE_CONNECTOR_ID",
    "SignedToolRegistry",
]
