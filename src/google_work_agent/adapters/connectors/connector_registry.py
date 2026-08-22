"""Fail-closed connector backend registry.

The registry owns connector-id to backend selection. It deliberately has no
default connector and performs no tool-name/provider inference: callers must
supply the persisted/bound connector identity explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.connectors.connector_not_registered_error import (
    ConnectorNotRegisteredError,
)


class ConnectorRegistry[BackendT]:
    """Immutable connector-id keyed backend authority."""

    def __init__(self, backends: Mapping[str, BackendT]) -> None:
        normalized = dict(backends)
        if not normalized:
            raise ValueError("connector registry requires at least one backend")
        if any(not connector_id for connector_id in normalized):
            raise ValueError("connector registry ids must be non-empty")
        self._backends = normalized

    @property
    def registered_connector_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))

    def resolve(self, connector_id: str) -> BackendT:
        if not connector_id:
            raise ValueError("connector resolution requires a non-empty connector id")
        try:
            return self._backends[connector_id]
        except KeyError as error:
            raise ConnectorNotRegisteredError(
                f"connector backend not registered: {connector_id}"
            ) from error
