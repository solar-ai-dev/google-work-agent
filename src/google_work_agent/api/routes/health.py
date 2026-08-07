"""Health routes."""

from fastapi import APIRouter, Request

from google_work_agent.adapters.readiness.composite import compose_readiness
from google_work_agent.api.dependencies import enforce_access, get_container
from google_work_agent.api.schemas.runtime import LiveResponse, ReadyResponse
from google_work_agent.ports import EndpointPolicy, ReadinessCheckResult, ReadinessState

router = APIRouter()


@router.get("/health/live", response_model=LiveResponse)
def live(request: Request) -> LiveResponse:
    enforce_access(request, policy=EndpointPolicy.HEALTH_PUBLIC)
    container = get_container(request)
    return LiveResponse(
        status="LIVE",
        service_instance_id=container.service_instance_id,
        release_version=container.release_version,
        api_contract_version=container.api_contract_version,
        occurred_at_ms=container.clock.now_ms(),
    )


@router.get("/health/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    enforce_access(request, policy=EndpointPolicy.HEALTH_PUBLIC)
    container = get_container(request)
    report = container.readiness_aggregator.evaluate()
    checks = list(report.checks)
    state = report.state
    verifier = container.launcher_probe_verifier
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
        probe = verifier.verify(service_instance_id=container.service_instance_id)
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
    if container.frontend_site is not None:
        checks.append(container.frontend_site.readiness_check())
    if container.safe_mode_controller is not None:
        checks.append(container.safe_mode_controller.readiness_check())
    for factory in container.additional_readiness_checks:
        checks.append(factory())
    state = compose_readiness(tuple(checks)).state
    return ReadyResponse(
        status=state.value,
        checks=[
            {"name": check.name, "state": check.state.value, "detail": check.detail}
            for check in checks
        ],
        release_version=container.release_version,
        api_contract_version=container.api_contract_version,
        occurred_at_ms=container.clock.now_ms(),
    )
