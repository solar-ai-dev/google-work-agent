"""Test-only MCP child used by transport contract tests."""

from __future__ import annotations

import json
import os
import sys
from typing import cast

from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.domain.google_workspace_tool_contracts import (
    google_workspace_tool_contract,
)
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)


def main() -> None:
    for line in sys.stdin:
        request = cast(dict[str, object], json.loads(line))
        request_id = request.get("id", "")
        message_type = request.get("type")
        payload: dict[str, object]
        if message_type == "shutdown":
            return
        if message_type == "handshake":
            payload = {"process_instance_id": "test-mcp"}
        elif message_type == "initialize":
            payload = {
                "protocol_version": "2026-08-07.p0",
                "manifest_version": request["manifest_version"],
                "tool_registry_version": request["tool_registry_version"],
                "internal_capability_registry_version": (
                    INTERNAL_CAPABILITY_REGISTRY_VERSION
                ),
            }
        elif message_type == "list_tools":
            payload = {
                "tool_names": sorted(
                    entry.tool_name
                    for entry in build_google_workspace_tool_registry().list_entries()
                )
            }
        elif message_type == "control_call":
            payload = _control_payload(str(request.get("method", "")))
        elif message_type == "tool_call":
            arguments = cast(dict[str, object], request.get("arguments") or {})
            if arguments.get("__test_exit_after_dispatch") is True:
                os._exit(0)
            certainty = arguments.get("__test_delivery_certainty")
            if isinstance(certainty, str):
                sys.stdout.write(
                    json.dumps(
                        {
                            "id": request_id,
                            "error": {
                                "code": "TOOL_REJECTED",
                                "message": "delivery-certainty-fixture",
                                "delivery_certainty": certainty,
                                "dispatch_started": certainty != "NOT_SENT",
                            },
                        }
                    )
                    + "\n"
                )
                sys.stdout.flush()
                continue
            payload = {}
        else:
            payload = {}
        sys.stdout.write(json.dumps({"id": request_id, "payload": payload}) + "\n")
        sys.stdout.flush()


def _control_payload(method: str) -> dict[str, object]:
    if method == "mcp.list_internal_capabilities":
        return {
            "internal_capability_registry_version": INTERNAL_CAPABILITY_REGISTRY_VERSION,
            "internal_capability_names": sorted(
                capability.tool_name
                for capability in build_google_workspace_internal_capabilities()
            ),
        }
    if method == "mcp.list_capability_contracts":
        internal_categories = {
            capability.tool_name: capability.category.value
            for capability in build_google_workspace_internal_capabilities()
        }
        names = {
            entry.tool_name for entry in build_google_workspace_tool_registry().list_entries()
        } | set(internal_categories)
        return {
            "contracts": [
                {
                    "tool_name": name,
                    "category": internal_categories.get(name, "AGENT_TOOL"),
                    "input_schema_version": (
                        google_workspace_tool_contract(name).input_schema_version
                    ),
                    "output_schema_version": (
                        google_workspace_tool_contract(name).output_schema_version
                    ),
                    "tool_schema_hash": google_workspace_tool_contract(name).schema_hash,
                }
                for name in sorted(names)
            ]
        }
    return {
        "connected": False,
        "credential_state": "NOT_CONNECTED",
        "account_email": None,
        "display_name": None,
        "granted_scopes": [],
        "missing_scopes": [],
        "reauth_required": False,
        "oauth_environment": "DEVELOPMENT",
        "last_checked_at_ms": 0,
    }


if __name__ == "__main__":
    main()
