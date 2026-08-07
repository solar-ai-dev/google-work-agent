"""Launcher probe verification contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.ports.readiness import ReadinessCheckResult


@dataclass(frozen=True, slots=True)
class LauncherProbeDecision:
    """Verification result for the local launcher handshake."""

    allowed: bool
    detail: str | None = None


class LauncherProbeVerifier(Protocol):
    """Verify that readiness is being queried by the local launcher."""

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        """Return whether the readiness caller satisfied the launcher handshake."""


class LauncherProbeCheckFactory(Protocol):
    """Optional helper that can derive a readiness check from the probe decision."""

    def build_check(self, *, service_instance_id: str) -> ReadinessCheckResult:
        """Return the readiness check that should be appended to `/health/ready`."""
