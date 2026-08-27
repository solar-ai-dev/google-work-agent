"""Compatibility wrapper for READ result persistence.

Connector identity is persisted on the Action and consumed explicitly by the
READ lifecycle, so ResourceRef persistence has no ContextVar dependency.
"""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.read_contracts import (
    CompleteReadActionCommand,
    ReadActionCommandResponse,
)
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.ports import UnitOfWork


class ConnectorBoundCompleteReadActionHandler(CompleteReadActionHandler):
    """Backward-compatible facade; connector persistence is explicit in delegate."""

    def __init__(
        self,
        *,
        delegate: CompleteReadActionHandler,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._delegate = delegate
        self._connector_uow_factory = unit_of_work_factory

    def __call__(self, command: CompleteReadActionCommand) -> ReadActionCommandResponse:
        return self._delegate(command)
