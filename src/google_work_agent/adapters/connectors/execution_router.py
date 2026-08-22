"""Connector-id keyed execution routing for legacy write-safety services.

The application ``ConnectorExecutionPort`` intentionally contains only provider
mechanics and therefore has no connector-selection argument. Until the legacy
write services are migrated to a connector-aware command contract, the
LangGraph adapter binds the already-persisted Action connector identity around
one execution/recovery phase and this router dispatches every port call through
the connector registry to that exact backend.

There is deliberately no tool-name inference and no default-provider fallback.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from google_work_agent.adapters.connectors.connector_registry import ConnectorRegistry
from google_work_agent.application.ports import (
    ConnectorExecutionPort,
    ConnectorWriteRequest,
    PreparedConnectorWrite,
)
from google_work_agent.ports import ResourceSnapshot

_execution_connector_id: ContextVar[str | None] = ContextVar(
    "execution_connector_id", default=None
)


@contextmanager
def bind_execution_connector_id(connector_id: str) -> Iterator[None]:
    """Bind one deterministic connector identity for a bounded execution phase."""

    if not connector_id:
        raise ValueError("execution connector binding requires a non-empty connector id")
    token = _execution_connector_id.set(connector_id)
    try:
        yield
    finally:
        _execution_connector_id.reset(token)


class ConnectorExecutionRouter(ConnectorExecutionPort):
    """Adapt the current execution Port onto explicit connector-registry lookup."""

    def __init__(self, backends: Mapping[str, ConnectorExecutionPort]) -> None:
        self._registry = ConnectorRegistry(backends)

    @property
    def registered_connector_ids(self) -> tuple[str, ...]:
        return self._registry.registered_connector_ids

    @property
    def last_request_id(self) -> str | None:
        """Expose the active backend's MCP request id without selecting another backend."""

        backend = self._active_backend()
        value = getattr(backend, "last_request_id", None)
        return value if isinstance(value, str) else None

    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedConnectorWrite:
        return self._active_backend().prepare_write(
            tool_name=tool_name,
            arguments=arguments,
            recovery_fingerprint=recovery_fingerprint,
        )

    def execute_write(self, request: ConnectorWriteRequest) -> ResourceSnapshot:
        return self._active_backend().execute_write(request)

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot:
        return self._active_backend().fetch_verification_snapshot(
            tool_name=tool_name,
            arguments=arguments,
            fallback_resource_id=fallback_resource_id,
        )

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        return self._active_backend().search_recovery_candidates(
            tool_name=tool_name,
            recovery_fingerprint=recovery_fingerprint,
        )

    def _active_backend(self) -> ConnectorExecutionPort:
        connector_id = _execution_connector_id.get()
        if connector_id is None:
            raise RuntimeError("connector execution attempted without a bound connector id")
        return self._registry.resolve(connector_id)
