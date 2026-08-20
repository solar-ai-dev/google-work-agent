"""Bind write-result ResourceRefs to the connector persisted on their Action."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from google_work_agent.adapters.persistence.connector_identity import (
    bind_resource_connector_id,
)
from google_work_agent.application.write_actions import (
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    WriteActionResponse,
)
from google_work_agent.ports import UnitOfWork


class _ConnectorAwareActionRepository(Protocol):
    def connector_id_for_action(self, action_id: str) -> str: ...


class ConnectorBoundStoreWriteActionSuccessService(StoreWriteActionSuccessService):
    """Delegate write-result persistence under the Action's frozen connector identity."""

    def __init__(
        self,
        *,
        delegate: StoreWriteActionSuccessService,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._delegate = delegate
        self._connector_uow_factory = unit_of_work_factory

    def __call__(self, command: StoreWriteActionSuccessCommand) -> WriteActionResponse:
        with self._connector_uow_factory() as unit_of_work:
            repository = cast(_ConnectorAwareActionRepository, unit_of_work.actions)
            connector_id = repository.connector_id_for_action(command.action_id)
        with bind_resource_connector_id(connector_id):
            return self._delegate(command)
