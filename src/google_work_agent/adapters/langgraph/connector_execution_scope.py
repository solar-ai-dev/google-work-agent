"""Bind persisted Action connector identity around external execution/recovery phases."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from google_work_agent.adapters.connectors.execution_router import bind_execution_connector_id
from google_work_agent.application.execution_phase import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
    WriteExecutionPhaseResult,
)
from google_work_agent.application.write_actions import WriteActionResponse
from google_work_agent.ports import UnitOfWork


class ConnectorBoundWriteExecutionPhaseCoordinator(WriteExecutionPhaseCoordinator):
    """Route external execution using the connector persisted on the Action.

    The delegate still owns safety sequencing.  This facade is regression-only
    IMP-304 plumbing: it binds the already-frozen Action connector to execution
    routing. ResourceRef persistence receives connector_id explicitly from the
    Action record and is intentionally not bound here.
    """

    def __init__(
        self,
        *,
        delegate: WriteExecutionPhaseCoordinator,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._delegate = delegate
        self._connector_uow_factory = unit_of_work_factory

    def execute(self, request: WriteExecutionPhaseRequest) -> WriteExecutionPhaseResult:
        with self._connector_scope(request.action_id):
            return self._delegate.execute(request)

    def recover_unknown(self, request: UnknownRecoveryPhaseRequest) -> WriteActionResponse:
        with self._connector_scope(request.action_id):
            return self._delegate.recover_unknown(request)

    def verify_executed(
        self,
        *,
        action_id: str,
        action_version: int,
        attempt_id: str,
        request_kind: str,
    ) -> WriteActionResponse:
        with self._connector_scope(action_id):
            return self._delegate.verify_executed(
                action_id=action_id,
                action_version=action_version,
                attempt_id=attempt_id,
                request_kind=request_kind,
            )

    @contextmanager
    def _connector_scope(self, action_id: str) -> Iterator[None]:
        with self._connector_uow_factory() as unit_of_work:
            connector_id = unit_of_work.actions.connector_id_for_action(action_id)
        if not connector_id:
            raise ValueError("persisted action connector_id is required for execution routing")
        with bind_execution_connector_id(connector_id):
            yield
