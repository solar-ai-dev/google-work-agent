"""Compatibility wrapper for write-result persistence.

Connector identity is now carried explicitly by the persisted Action and the
application ResourceRef projector, so no persistence ContextVar is required.
"""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.write_actions import (
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    WriteActionResponse,
)
from google_work_agent.ports import UnitOfWork


class ConnectorBoundStoreWriteActionSuccessService(StoreWriteActionSuccessService):
    """Backward-compatible facade; connector persistence is explicit in delegate."""

    def __init__(
        self,
        *,
        delegate: StoreWriteActionSuccessService,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._delegate = delegate
        self._connector_uow_factory = unit_of_work_factory

    def __call__(self, command: StoreWriteActionSuccessCommand) -> WriteActionResponse:
        return self._delegate(command)