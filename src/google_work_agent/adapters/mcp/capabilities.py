"""Explicit non-Agent MCP capability registry for Google Workspace.

Agent routing continues to use ``SignedToolRegistry``. UI, attachment, and
recovery-only callables live here so they can be signed/versioned in the MCP
manifest without becoming eligible Agent tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

INTERNAL_CAPABILITY_REGISTRY_VERSION = "2026-08-20.p0"


class MCPInternalCapabilityCategory(StrEnum):
    """Non-Agent callable capability categories exposed by the MCP child."""

    UI_READ = "UI_READ"
    ATTACHMENT_READ = "ATTACHMENT_READ"
    RECOVERY_READ = "RECOVERY_READ"


@dataclass(frozen=True, slots=True)
class MCPInternalCapability:
    """Versioned declaration for one non-Agent MCP callable.

    Input/output schema versions are explicit here, while the actual schema
    authority/hash is closed separately by Task 7-B. This registry must not be
    used by Tool Route candidate selection.
    """

    tool_name: str
    category: MCPInternalCapabilityCategory
    input_schema_version: str = "v1"
    output_schema_version: str = "v1"
    registry_version: str = INTERNAL_CAPABILITY_REGISTRY_VERSION

    def to_manifest_payload(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "category": self.category.value,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "registry_version": self.registry_version,
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
