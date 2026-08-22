"""Application-owned registry of configured connector runtime handles."""

from __future__ import annotations

from google_work_agent.ports.connectors.connector_runtime import ConnectorRuntimeHandle


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, ConnectorRuntimeHandle] = {}

    def register(self, connector: ConnectorRuntimeHandle) -> None:
        connector_id = connector.connector_id
        if connector_id in self._connectors:
            raise ValueError(f"connector already registered: {connector_id}")
        self._connectors[connector_id] = connector

    def get(self, connector_id: str) -> ConnectorRuntimeHandle:
        try:
            return self._connectors[connector_id]
        except KeyError as error:
            raise LookupError(f"connector not registered: {connector_id}") from error

    def contains(self, connector_id: str) -> bool:
        return connector_id in self._connectors

    def list_registered_connector_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))

    def close_all(self) -> None:
        for connector_id in reversed(self.list_registered_connector_ids()):
            self._connectors[connector_id].close()
