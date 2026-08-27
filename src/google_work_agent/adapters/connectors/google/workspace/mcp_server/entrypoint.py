"""Canonical Google Workspace MCP child entrypoint."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server.server_runtime import (
    main as _run_server,
)


class GoogleWorkspaceMcpServerEntrypoint:
    """Executable entrypoint for the capability-verified MCP child."""

    def run(self) -> None:
        _run_server()


def main() -> None:
    GoogleWorkspaceMcpServerEntrypoint().run()


__all__ = ["GoogleWorkspaceMcpServerEntrypoint", "main"]


if __name__ == "__main__":
    main()
