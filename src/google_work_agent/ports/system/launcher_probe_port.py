"""System-boundary launcher probe verification contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LauncherProbeDecision:
    """Verification result for the local launcher handshake."""

    allowed: bool
    detail: str | None = None


class LauncherProbeVerifier(Protocol):
    """Verify that readiness is being queried by the local launcher."""

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        """Return whether the readiness caller satisfied the launcher handshake."""
