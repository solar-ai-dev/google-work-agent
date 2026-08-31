"""Test-only Google Workspace MCP entrypoint with an in-memory secret store."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleWorkspaceCredentialProvider,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint import run_server


class _MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def put(self, key: str, secret_bytes: bytes) -> None:
        self._values[key] = bytes(secret_bytes)

    def get(self, key: str) -> bytes | None:
        return self._values.get(key)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


def main() -> None:
    store = _MemorySecretStore()
    run_server(lambda: GoogleWorkspaceCredentialProvider(keyring=store))


if __name__ == "__main__":
    main()
