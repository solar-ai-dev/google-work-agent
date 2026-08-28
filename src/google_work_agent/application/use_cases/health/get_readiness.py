"""Compose core readiness below the HTTP health projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google_work_agent.application.readiness import compose_readiness
from google_work_agent.ports import ReadinessCheckResult, ReadinessState


@dataclass(frozen=True, slots=True)
class GetReadinessQuery:
    service_instance_id: str


@dataclass(frozen=True, slots=True)
class GetReadinessResult:
    state: ReadinessState
    checks: tuple[ReadinessCheckResult, ...]


class GetReadinessHandler:
    """Own readiness composition while HTTP owns access and wire projection."""

    def __init__(
        self,
        *,
        readiness_aggregator_factory: Callable[[], Any],
        launcher_probe_verifier: Any | None,
        frontend_readiness_check: Callable[[], ReadinessCheckResult] | None,
        safe_mode_readiness_check: Callable[[], ReadinessCheckResult] | None,
        additional_readiness_checks: tuple[Callable[[], ReadinessCheckResult], ...],
    ) -> None:
        self._readiness_aggregator_factory = readiness_aggregator_factory
        self._launcher_probe_verifier = launcher_probe_verifier
        self._frontend_readiness_check = frontend_readiness_check
        self._safe_mode_readiness_check = safe_mode_readiness_check
        self._additional_readiness_checks = additional_readiness_checks

    def handle(self, query: GetReadinessQuery) -> GetReadinessResult:
        report = self._readiness_aggregator_factory().evaluate()
        checks = list(report.checks)
        verifier = self._launcher_probe_verifier
        if verifier is None:
            checks.append(
                ReadinessCheckResult(
                    name="launcher_probe",
                    state=ReadinessState.NOT_READY,
                    detail="launcher probe verifier missing",
                )
            )
        else:
            probe = verifier.verify(service_instance_id=query.service_instance_id)
            checks.append(
                ReadinessCheckResult(
                    name="launcher_probe",
                    state=(
                        ReadinessState.READY
                        if probe.allowed
                        else ReadinessState.NOT_READY
                    ),
                    detail=(
                        None
                        if probe.allowed
                        else probe.detail or "launcher probe denied"
                    ),
                )
            )
        if self._frontend_readiness_check is not None:
            checks.append(self._frontend_readiness_check())
        if self._safe_mode_readiness_check is not None:
            checks.append(self._safe_mode_readiness_check())
        for factory in self._additional_readiness_checks:
            checks.append(factory())
        return GetReadinessResult(
            state=compose_readiness(tuple(checks)).state,
            checks=tuple(checks),
        )
