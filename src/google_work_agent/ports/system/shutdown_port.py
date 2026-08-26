"""Graceful shutdown boundary."""

from typing import Protocol

from google_work_agent.ports.runtime_contracts import ShutdownReport


class ShutdownPort(Protocol):
    def shutdown(self, *, timeout_seconds: float) -> ShutdownReport: ...
