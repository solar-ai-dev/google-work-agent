"""Signed tool registry contract for the P0 product core."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps

from google_work_agent.domain.enums import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)

DEFAULT_POLICY_VERSION = "2026-08-06.p0"
DEFAULT_TOOL_SCHEMA_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ToolRegistryEntry:
    """Deterministic policy snapshot for one registered tool."""

    tool_name: str
    resource_type: str
    effect_type: EffectType
    approval_requirement: ApprovalRequirement
    verification_policy: VerificationPolicy
    recovery_policy: RecoveryPolicy
    scope: str
    retryable: bool
    input_schema_version: str = DEFAULT_TOOL_SCHEMA_VERSION
    output_schema_version: str = DEFAULT_TOOL_SCHEMA_VERSION
    registry_version: str = DEFAULT_POLICY_VERSION
    tool_schema_hash: str = ""
    # FN-052 Action Modify authority for this tool -- NOT the tool's full MCP
    # dispatch-time mutable capability. See the module-level comment above.
    modify_patchable_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.tool_schema_hash:
            return
        payload = dumps(
            {
                "tool_name": self.tool_name,
                "resource_type": self.resource_type,
                "effect_type": self.effect_type.value,
                "approval_requirement": self.approval_requirement.value,
                "verification_policy": self.verification_policy.value,
                "recovery_policy": self.recovery_policy.value,
                "scope": self.scope,
                "retryable": self.retryable,
                "input_schema_version": self.input_schema_version,
                "output_schema_version": self.output_schema_version,
                "registry_version": self.registry_version,
                "modify_patchable_fields": sorted(self.modify_patchable_fields),
            },
            sort_keys=True,
        ).encode("utf-8")
        object.__setattr__(self, "tool_schema_hash", sha256(payload).hexdigest())


class SignedToolRegistry:
    """Immutable lookup wrapper over a fixed tool registry snapshot."""

    def __init__(self, entries: tuple[ToolRegistryEntry, ...]) -> None:
        self._entries = {entry.tool_name: entry for entry in entries}
        if len(self._entries) != len(entries):
            raise ValueError("tool registry contains duplicate tool_name values")

    def get(self, tool_name: str) -> ToolRegistryEntry | None:
        """Return the registry entry for a tool, if registered."""

        return self._entries.get(tool_name)

    def require(self, tool_name: str) -> ToolRegistryEntry:
        """Return the registry entry or fail for unregistered tools."""

        entry = self.get(tool_name)
        if entry is None:
            raise LookupError(f"tool not registered: {tool_name}")
        return entry

    def list_entries(self) -> tuple[ToolRegistryEntry, ...]:
        """Return the full registry snapshot in sorted tool-name order."""

        return tuple(sorted(self._entries.values(), key=lambda entry: entry.tool_name))

    def eligible(
        self,
        *,
        resource_type: str,
        effect_type: EffectType,
    ) -> tuple[ToolRegistryEntry, ...]:
        """Return deterministic candidates for one semantic resource/effect pair."""

        return tuple(
            entry
            for entry in self.list_entries()
            if entry.resource_type == resource_type and entry.effect_type is effect_type
        )


class ConnectorToolCatalog:
    """Lookup catalog keyed by connector id and existing public tool id."""

    def __init__(self) -> None:
        self._registries: dict[str, SignedToolRegistry] = {}

    def register(self, *, connector_id: str, registry: SignedToolRegistry) -> None:
        if connector_id in self._registries:
            raise ValueError(f"connector tool registry already registered: {connector_id}")
        self._registries[connector_id] = registry

    def contains(self, connector_id: str) -> bool:
        return connector_id in self._registries

    def list_connector_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registries))

    def registry_for(self, connector_id: str) -> SignedToolRegistry:
        try:
            return self._registries[connector_id]
        except KeyError as error:
            raise LookupError(f"connector tool registry not registered: {connector_id}") from error

    def require(self, *, connector_id: str, tool_id: str) -> ToolRegistryEntry:
        return self.registry_for(connector_id).require(tool_id)

    def eligible(
        self,
        *,
        connector_id: str,
        resource_type: str,
        effect_type: EffectType,
    ) -> tuple[ToolRegistryEntry, ...]:
        return self.registry_for(connector_id).eligible(
            resource_type=resource_type,
            effect_type=effect_type,
        )


def build_p0_tool_registry() -> SignedToolRegistry:
    """Compatibility wrapper for the P0 Google Workspace registry."""

    from google_work_agent.domain.google_workspace_tool_registry import (
        build_google_workspace_tool_registry,
    )

    return build_google_workspace_tool_registry()
