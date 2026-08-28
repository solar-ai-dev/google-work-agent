"""System-boundary readiness and runtime summary contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ReadinessState(StrEnum):
    """Readiness states exposed through `/health/ready`."""

    READY = "READY"
    NOT_READY = "NOT_READY"
    SAFE_MODE = "SAFE_MODE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True, slots=True)
class ReadinessCheckResult:
    """Outcome of one readiness check."""

    name: str
    state: ReadinessState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregated readiness report."""

    state: ReadinessState
    checks: tuple[ReadinessCheckResult, ...]


class ReadinessAggregator(Protocol):
    """Compute the current readiness report."""

    def evaluate(self) -> ReadinessReport:
        """Return one readiness report."""
