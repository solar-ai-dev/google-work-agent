"""Graceful shutdown boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass(frozen=True, slots=True)
class ShutdownAcceptedV1:
    schema_version: Literal[1]
    accepted: bool


class ShutdownPort(Protocol):
    def request_shutdown(self, operation_ref: str) -> ShutdownAcceptedV1: ...

    def reconcile_shutdown(self, operation_ref: str) -> OperationalReconcileResultV1: ...


__all__ = ["ShutdownAcceptedV1", "ShutdownPort"]
