"""Explicit non-Agent MCP capability registry for Google Workspace.

Agent routing continues to use ``SignedToolRegistry``. UI, attachment, and
recovery-only callables live here so they can be signed/versioned/schema-bound
without becoming eligible Agent tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.google_workspace_tool_contracts import (
    GoogleWorkspaceToolContract,
    google_workspace_tool_contract,
)

INTERNAL_CAPABILITY_REGISTRY_VERSION = "2026-08-20.p0"


class MCPInternalCapabilityCategory(StrEnum):
    """Non-Agent callable capability categories exposed by the MCP child."""

    UI_READ = "UI_READ"
    ATTACHMENT_READ = "ATTACHMENT_READ"
    RECOVERY_READ = "RECOVERY_READ"


@dataclass(frozen=True, slots=True)
class MCPInternalCapability:
    """Versioned declaration for one non-Agent MCP callable."""

    tool_name: str
    category: MCPInternalCapabilityCategory
    registry_version: str = INTERNAL_CAPABILITY_REGISTRY_VERSION

    @property
    def contract(self) -> GoogleWorkspaceToolContract:
        return google_workspace_tool_contract(self.tool_name)

    @property
    def input_schema_version(self) -> str:
        return self.contract.input_schema_version

    @property
    def output_schema_version(self) -> str:
        return self.contract.output_schema_version

    @property
    def tool_schema_hash(self) -> str:
        return self.contract.schema_hash

    def to_manifest_payload(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "category": self.category.value,
            "registry_version": self.registry_version,
            **self.contract.manifest_schema_payload(),
        }


def build_google_workspace_internal_capabilities() -> tuple[MCPInternalCapability, ...]:
    """Return the complete Google Workspace non-Agent callable surface."""

    return (
        MCPInternalCapability(
            tool_name="gmail_get_attachment",
            category=MCPInternalCapabilityCategory.ATTACHMENT_READ,
        ),
        MCPInternalCapability(
            tool_name="gmail_get_ui_thread_detail",
            category=MCPInternalCapabilityCategory.UI_READ,
        ),
        MCPInternalCapability(
            tool_name="search_by_recovery_fingerprint",
            category=MCPInternalCapabilityCategory.RECOVERY_READ,
        ),
    )
