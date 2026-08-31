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


def compose_readiness(checks: tuple[ReadinessCheckResult, ...]) -> ReadinessReport:
    """Derive the aggregate service state from its individual checks."""

    if any(check.state is ReadinessState.SAFE_MODE for check in checks):
        state = ReadinessState.SAFE_MODE
    elif any(check.state is ReadinessState.NOT_READY for check in checks):
        state = ReadinessState.NOT_READY
    elif checks and all(check.state is ReadinessState.READY for check in checks):
        state = ReadinessState.READY
    else:
        state = ReadinessState.NOT_CONFIGURED
    return ReadinessReport(state=state, checks=checks)
