"""Composite readiness adapters for the local API."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import (
    LauncherProbeDecision,
    LauncherProbeVerifier,
    ReadinessAggregator,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeStatusProvider,
    RuntimeSummary,
)


@dataclass(frozen=True, slots=True)
class StaticReadinessAggregator(ReadinessAggregator):
    """Static readiness aggregator for tests and local composition."""

    report: ReadinessReport

    def evaluate(self) -> ReadinessReport:
        return self.report


@dataclass(frozen=True, slots=True)
class StaticRuntimeStatusProvider(RuntimeStatusProvider):
    """Static runtime status provider for tests and local composition."""

    summary: RuntimeSummary

    def get_summary(self) -> RuntimeSummary:
        return self.summary


@dataclass(frozen=True, slots=True)
class StaticLauncherProbeVerifier(LauncherProbeVerifier):
    """Static launcher probe verifier for tests and local composition."""

    decision: LauncherProbeDecision

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        del service_instance_id
        return self.decision


def compose_readiness(checks: tuple[ReadinessCheckResult, ...]) -> ReadinessReport:
    """Derive aggregate readiness from individual check states."""

    if any(check.state is ReadinessState.SAFE_MODE for check in checks):
        state = ReadinessState.SAFE_MODE
    elif any(check.state is ReadinessState.NOT_READY for check in checks):
        state = ReadinessState.NOT_READY
    elif checks and all(check.state is ReadinessState.READY for check in checks):
        state = ReadinessState.READY
    else:
        state = ReadinessState.NOT_CONFIGURED
    return ReadinessReport(state=state, checks=checks)
