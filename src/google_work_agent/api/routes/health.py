"""Health routes."""

from fastapi import APIRouter, Request

from google_work_agent.api.dependencies import get_container
from google_work_agent.api.schemas.runtime import LiveResponse, ReadyResponse

router = APIRouter()


@router.get("/health/live", response_model=LiveResponse)
def live(request: Request) -> LiveResponse:
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
    container = get_container(request)
    report = container.readiness_aggregator.evaluate()
    return ReadyResponse(
        status=report.state.value,
        checks=[
            {"name": check.name, "state": check.state.value, "detail": check.detail}
            for check in report.checks
        ],
        release_version=container.release_version,
        api_contract_version=container.api_contract_version,
        occurred_at_ms=container.clock.now_ms(),
    )
