"""Test-only MCP child used by transport contract tests."""

from __future__ import annotations

import json
import sys
from typing import cast

from google_work_agent.domain import build_p0_tool_registry


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
            }
        elif message_type == "list_tools":
            payload = {
                "tool_names": sorted(
                    entry.tool_name for entry in build_p0_tool_registry().list_entries()
                )
            }
        elif message_type == "control_call":
            payload = {
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
        else:
            payload = {}
        sys.stdout.write(json.dumps({"id": request_id, "payload": payload}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
