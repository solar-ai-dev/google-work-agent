"""Health-check route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.ports.system.clock_port import ClockPort
from google_work_agent.ports.system.launcher_probe_port import LauncherProbeVerifier
from google_work_agent.ports.system.readiness_port import (
    ReadinessAggregator,
    ReadinessCheckResult,
)


@dataclass(frozen=True, slots=True)
class HealthRouteDependencies:
    service_instance_id: str
    release_version: str
    api_contract_version: str
    clock: ClockPort
    readiness_aggregator: Callable[[], ReadinessAggregator]
    launcher_probe_verifier: LauncherProbeVerifier | None
    frontend_readiness_check: Callable[[], ReadinessCheckResult] | None
    safe_mode_readiness_check: Callable[[], ReadinessCheckResult] | None
    additional_readiness_checks: tuple[Callable[[], ReadinessCheckResult], ...]


def get_health_route_dependencies(request: Request) -> HealthRouteDependencies:
    container = get_api_container(request)
    frontend = container.frontend_site
    safe_mode = container.safe_mode_controller
    return HealthRouteDependencies(
        service_instance_id=container.service_instance_id,
        release_version=container.release_version,
        api_contract_version=container.api_contract_version,
        clock=container.clock,
        readiness_aggregator=lambda: container.readiness_aggregator,
        launcher_probe_verifier=container.launcher_probe_verifier,
        frontend_readiness_check=None if frontend is None else frontend.readiness_check,
        safe_mode_readiness_check=None if safe_mode is None else safe_mode.readiness_check,
        additional_readiness_checks=container.additional_readiness_checks,
    )


HealthRouteDependency = Annotated[
    HealthRouteDependencies,
    Depends(get_health_route_dependencies),
]
