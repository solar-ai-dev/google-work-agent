"""Request graceful local-service shutdown through Application authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class RequestShutdownCommand:
    """Explicit shutdown command."""


@dataclass(frozen=True, slots=True)
class RequestShutdownResult:
    report: dict[str, object]


class RequestShutdownHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: RequestShutdownCommand) -> RequestShutdownResult:
        del command
        service = self._service_factory()
        if service is None:
            raise RuntimeError("SHUTDOWN_UNAVAILABLE")
        return RequestShutdownResult(report=asdict(service()))
