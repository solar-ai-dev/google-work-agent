"""Readiness boundary test doubles."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.system.launcher_probe_port import (
    LauncherProbeDecision,
    LauncherProbeVerifier,
)
from google_work_agent.ports.system.readiness_port import ReadinessAggregator, ReadinessReport


@dataclass(frozen=True, slots=True)
class StaticReadinessAggregator(ReadinessAggregator):
    report: ReadinessReport

    def evaluate(self) -> ReadinessReport:
        return self.report


@dataclass(frozen=True, slots=True)
class StaticLauncherProbeVerifier(LauncherProbeVerifier):
    decision: LauncherProbeDecision

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        del service_instance_id
        return self.decision


__all__ = ["StaticLauncherProbeVerifier", "StaticReadinessAggregator"]
