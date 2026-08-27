"""Private invocation support for operation-per-file Google provider adapters."""

from __future__ import annotations

from typing import ClassVar, cast

from google_work_agent.adapters.connectors.google.workspace.mcp_server import workspace_runtime


class WorkspaceProviderOperation:
    """Bind one canonical provider operation class to one private runtime handler."""

    tool_id: ClassVar[str]

    def execute(
        self,
        state: workspace_runtime._WorkspaceState,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        handler = getattr(workspace_runtime, f"_{self.tool_id}", None)
        if not callable(handler):
            raise workspace_runtime._WorkspaceToolError("TOOL_NOT_AVAILABLE")
        return cast(dict[str, object], handler(state, arguments))


__all__ = ["WorkspaceProviderOperation"]
