"""Process liveness and infrastructure readiness routes."""

from fastapi import APIRouter, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.health_checks import HealthRouteDependency
from google_work_agent.api.schemas.health_checks.get_liveness import LiveResponse
from google_work_agent.api.schemas.health_checks.get_readiness import ReadyResponse
from google_work_agent.launcher.get_readiness import (
    GetReadinessHandler,
    GetReadinessQuery,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter()


@router.get("/health/live", response_model=LiveResponse)
def live(request: Request, dependencies: HealthRouteDependency) -> LiveResponse:
    enforce_access(request, policy=EndpointPolicy.HEALTH_PUBLIC)
    return LiveResponse(
        status="LIVE",
        service_instance_id=dependencies.service_instance_id,
        release_version=dependencies.release_version,
        api_contract_version=dependencies.api_contract_version,
        occurred_at_ms=dependencies.clock.now_ms(),
    )


@router.get("/health/ready", response_model=ReadyResponse)
def ready(request: Request, dependencies: HealthRouteDependency) -> ReadyResponse:
    enforce_access(request, policy=EndpointPolicy.HEALTH_PUBLIC)
    result = GetReadinessHandler(
        readiness_aggregator_factory=dependencies.readiness_aggregator,
        launcher_probe_verifier=dependencies.launcher_probe_verifier,
        frontend_readiness_check=dependencies.frontend_readiness_check,
        safe_mode_readiness_check=dependencies.safe_mode_readiness_check,
        additional_readiness_checks=dependencies.additional_readiness_checks,
    ).handle(GetReadinessQuery(service_instance_id=dependencies.service_instance_id))
    return ReadyResponse(
        status=result.state.value,
        checks=[
            {"name": check.name, "state": check.state.value, "detail": check.detail}
            for check in result.checks
        ],
        release_version=dependencies.release_version,
        api_contract_version=dependencies.api_contract_version,
        occurred_at_ms=dependencies.clock.now_ms(),
    )
