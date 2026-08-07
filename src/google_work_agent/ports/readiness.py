"""Readiness and runtime summary contracts."""

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


@dataclass(frozen=True, slots=True)
class RuntimeSummary:
    """Runtime summary returned to the local UI."""

    google: str
    mcp: str
    api_llm: str
    ollama: str
    deployment_profile: str
    recovery_required_run_ids: tuple[str, ...]
    open_run_ids: tuple[str, ...]


class ReadinessAggregator(Protocol):
    """Compute the current readiness report."""

    def evaluate(self) -> ReadinessReport:
        """Return one readiness report."""


class RuntimeStatusProvider(Protocol):
    """Provide dependency status without contacting real external systems."""

    def get_summary(self) -> RuntimeSummary:
        """Return the current runtime summary."""
