"""Health routes."""

from fastapi import APIRouter, Request

from google_work_agent.api.dependencies import (
    HealthRouteDependency,
    composed_readiness_state,
    enforce_access,
)
from google_work_agent.api.schemas.runtime import LiveResponse, ReadyResponse
from google_work_agent.ports import EndpointPolicy, ReadinessCheckResult, ReadinessState

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
    report = dependencies.readiness_aggregator().evaluate()
    checks = list(report.checks)
    state = report.state
    verifier = dependencies.launcher_probe_verifier
    if verifier is None:
        checks.append(
            ReadinessCheckResult(
                name="launcher_probe",
                state=ReadinessState.NOT_READY,
                detail="launcher probe verifier missing",
            )
        )
        state = ReadinessState.NOT_READY
    else:
        probe = verifier.verify(service_instance_id=dependencies.service_instance_id)
        if probe.allowed:
            checks.append(ReadinessCheckResult(name="launcher_probe", state=ReadinessState.READY))
        else:
            checks.append(
                ReadinessCheckResult(
                    name="launcher_probe",
                    state=ReadinessState.NOT_READY,
                    detail=probe.detail or "launcher probe denied",
                )
            )
            state = ReadinessState.NOT_READY
    if dependencies.frontend_readiness_check is not None:
        checks.append(dependencies.frontend_readiness_check())
    if dependencies.safe_mode_readiness_check is not None:
        checks.append(dependencies.safe_mode_readiness_check())
    for factory in dependencies.additional_readiness_checks:
        checks.append(factory())
    state = composed_readiness_state(tuple(checks))
    return ReadyResponse(
        status=state.value,
        checks=[
            {"name": check.name, "state": check.state.value, "detail": check.detail}
            for check in checks
        ],
        release_version=dependencies.release_version,
        api_contract_version=dependencies.api_contract_version,
        occurred_at_ms=dependencies.clock.now_ms(),
    )
