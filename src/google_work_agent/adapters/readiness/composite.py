"""Composite readiness adapters for the local API."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.launcher.readiness_projection import compose_readiness
from google_work_agent.ports.system.launcher_probe_port import (
    LauncherProbeDecision,
    LauncherProbeVerifier,
)
from google_work_agent.ports.system.readiness_port import (
    ReadinessAggregator,
    ReadinessReport,
)

__all__ = [
    "StaticLauncherProbeVerifier",
    "StaticReadinessAggregator",
    "compose_readiness",
]


@dataclass(frozen=True, slots=True)
class StaticReadinessAggregator(ReadinessAggregator):
    """Static readiness aggregator for tests and local composition."""

    report: ReadinessReport

    def evaluate(self) -> ReadinessReport:
        return self.report


@dataclass(frozen=True, slots=True)
class StaticLauncherProbeVerifier(LauncherProbeVerifier):
    """Static launcher probe verifier for tests and local composition."""

    decision: LauncherProbeDecision

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        del service_instance_id
        return self.decision
