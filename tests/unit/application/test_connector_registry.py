from dataclasses import dataclass

import pytest

from google_work_agent.application.connector_registry import ConnectorRegistry
from google_work_agent.ports import MCPRuntimeMetadata, MCPTransport


@dataclass
class _Connector:
    connector_id: str
    close_count: int = 0

    def start(self) -> MCPTransport:
        raise NotImplementedError

    def health(self) -> MCPRuntimeMetadata:
        return _metadata()

    def restart(self) -> MCPRuntimeMetadata:
        return _metadata()

    def close(self) -> None:
        self.close_count += 1


def test_connector_registry_registers_and_lists_google_workspace() -> None:
    registry = ConnectorRegistry()
    connector = _Connector("google_workspace")

    registry.register(connector)

    assert registry.contains("google_workspace")
    assert registry.get("google_workspace") is connector
    assert registry.list_registered_connector_ids() == ("google_workspace",)


def test_connector_registry_rejects_duplicate_connector_id() -> None:
    registry = ConnectorRegistry()
    registry.register(_Connector("google_workspace"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_Connector("google_workspace"))


def test_connector_registry_rejects_unknown_connector_lookup() -> None:
    with pytest.raises(LookupError, match="not registered"):
        ConnectorRegistry().get("unknown")


def test_connector_registry_closes_registered_runtime() -> None:
    connector = _Connector("google_workspace")
    registry = ConnectorRegistry()
    registry.register(connector)

    registry.close_all()

    assert connector.close_count == 1


def _metadata() -> MCPRuntimeMetadata:
    return MCPRuntimeMetadata(
        process_status="READY",
        protocol_version="v1",
        manifest_version="v1",
        tool_registry_version="v1",
        available_tool_count=1,
        last_safe_error_code=None,
        restart_count=0,
    )
